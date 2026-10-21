"""
tests/test_saas_sprint2_rbac.py — SaaS Sprint 2 RBAC, Token Invalidation, and Job IDOR Protection.
Validates:
- Pillar 2: Token versioning and immediate invalidation on role changes
- Pillar 6: Background job tenant isolation and cross-tenant IDOR defense
- Pillar 11: Sole organization owner protection and atomic folder permissions
"""
import pytest
from fastapi.testclient import TestClient

from main import app
from src.core.tenant_context import get_current_tenant_id, reset_tenant_context, set_current_tenant_id
from src.modules.auth.jwt_manager import create_access_token, decode_access_token
from src.modules.infra.postgres_repository import get_repository
from src.services.user_auth_service import get_auth_service
from src.services.jobs import create_job, get_job_status
from src.tasks.base import TenantAwareTask

client = TestClient(app)


class TestSprint2AuthAndTokenVersioning:
    """Pillar 2: Authentication & Instant Token Invalidation via Token Versioning."""

    def test_token_creation_and_version_stamping(self):
        """Verify token is issued with token_version in payload."""
        token = create_access_token(
            user_id="usr_test_v1",
            role="editor",
            tenant_id="tenant_sprint2_a",
            token_version=2,
        )
        payload = decode_access_token(token)
        assert payload is not None
        assert payload["sub"] == "usr_test_v1"
        assert payload["tenant_id"] == "tenant_sprint2_a"
        assert payload["role"] == "editor"
        assert payload["token_version"] == 2

    def test_immediate_token_invalidation_on_cache_flush(self):
        """Verify that when a user's auth cache is invalidated, previous tokens are immediately rejected."""
        import uuid
        rid = uuid.uuid4().hex[:8]
        repo = get_repository()
        service = get_auth_service()
        tid = f"tenant_inv_{rid}"
        uid = f"usr_rev_{rid}"

        repo.create_tenant(tid, "Inv Org")
        repo.create_user(
            user_id=uid,
            username=f"rev_{rid}",
            email=f"rev_{rid}@example.com",
            hashed_password="hashed_pw_xyz",
            role="editor",
            tenant_id=tid,
        )

        user = repo.get_user_by_id(uid, tenant_id=tid)
        assert user is not None
        initial_token = service.issue_token(user)

        # 1. Token should be valid initially
        verified_user = service.verify_token(initial_token)
        assert verified_user is not None
        assert verified_user["user_id"] == uid

        # 2. Invalidate user auth cache (e.g. role changed, demoted, or membership revoked)
        service.invalidate_auth_cache(tenant_id=tid, user_id=uid)

        # 3. Old token MUST immediately fail validation
        rejected_user = service.verify_token(initial_token)
        assert rejected_user is None, "Stale token must be rejected after invalidate_auth_cache"

        # 4. Issuing a new token should succeed and contain incremented token_version
        user_after = repo.get_user_by_id(uid, tenant_id=tid)
        assert user_after["token_version"] > user["token_version"]
        new_token = service.issue_token(user_after)
        assert service.verify_token(new_token) is not None


class TestSprint2BackgroundJobIsolationAndIDOR:
    """Pillar 6: Background Job Isolation & IDOR Protection."""

    @pytest.mark.asyncio
    async def test_cross_tenant_job_status_idor_blocked(self):
        """Verify a user from Tenant B cannot view a job from Tenant A (Anti-IDOR)."""
        import uuid
        rid = uuid.uuid4().hex[:8]
        tid_a = f"tenant_alpha_{rid}"
        tid_b = f"tenant_beta_{rid}"

        # Create job under Tenant A
        job_id = await create_job(
            user_id=f"usr_alpha_{rid}",
            folder="private_album",
            total_files=5,
            tenant_id=tid_a,
        )
        assert job_id is not None

        # 1. Tenant A lookup succeeds
        job_a = await get_job_status(job_id, tenant_id=tid_a)
        assert job_a is not None
        assert job_a["job_id"] == job_id
        assert job_a["tenant_id"] == tid_a

        # 2. Tenant B lookup fails with None (Preventing cross-tenant IDOR)
        job_b = await get_job_status(job_id, tenant_id=tid_b)
        assert job_b is None, "Cross-tenant job lookup must return None to prevent IDOR"

    def test_job_progress_api_idor_returns_404(self):
        """Verify the HTTP /api/jobs/{job_id} endpoint returns 404 for cross-tenant access."""
        import uuid
        uid_rand = uuid.uuid4().hex[:8]
        tid_a = f"tenant_http_alpha_{uid_rand}"
        tid_b = f"tenant_http_beta_{uid_rand}"
        u_a = f"usr_ha_{uid_rand}"
        u_b = f"usr_hb_{uid_rand}"
        jid = f"job_cross_{uid_rand}"
        repo = get_repository()

        # Seed users for both tenants
        repo.create_user(u_a, f"ha_{uid_rand}", f"ha_{uid_rand}@test.com", "pw", role="viewer", tenant_id=tid_a)
        repo.create_user(u_b, f"hb_{uid_rand}", f"hb_{uid_rand}@test.com", "pw", role="viewer", tenant_id=tid_b)

        token_a = create_access_token(user_id=u_a, role="viewer", tenant_id=tid_a)
        token_b = create_access_token(user_id=u_b, role="viewer", tenant_id=tid_b)

        # Create job under tenant A
        repo.create_job(job_id=jid, total_images=10, user_id=u_a, folder="photos", tenant_id=tid_a)

        # Tenant A can view its own job
        resp_a = client.get(f"/api/jobs/{jid}", headers={"Authorization": f"Bearer {token_a}"})
        assert resp_a.status_code == 200
        assert resp_a.json()["job_id"] == jid

        # Tenant B querying Tenant A's job receives 404 Not Found
        resp_b = client.get(f"/api/jobs/{jid}", headers={"Authorization": f"Bearer {token_b}"})
        assert resp_b.status_code == 404

    def test_tenant_aware_task_context_lifecycle(self):
        """Verify TenantAwareTask sets and resets tenant_id in execution lifecycle."""
        task = TenantAwareTask()
        task.name = "test_task"

        reset_tenant_context()
        assert get_current_tenant_id() == "default"

        # Task starts with tenant_id in kwargs
        task.before_start("task_123", (), {"tenant_id": "tenant_worker_isolation"})
        assert get_current_tenant_id() == "tenant_worker_isolation"

        # Task completes: tenant context must be cleanly reset
        task.after_return("SUCCESS", None, "task_123", (), {}, None)
        assert get_current_tenant_id() == "default"


class TestSprint2RoleManagementAndSoleOwner:
    """Pillar 11: Role & Membership Management & Sole Owner Protection."""

    def test_sole_owner_demotion_is_prevented(self):
        """Verify the sole owner of an organization cannot be demoted."""
        import uuid
        rid = uuid.uuid4().hex[:8]
        repo = get_repository()
        tid = f"tenant_sole_{rid}"
        owner_id = f"usr_sole_{rid}"

        repo.create_tenant(tid, "Sole Owner Org")
        repo.create_user(
            user_id=owner_id,
            username=f"sole_{rid}",
            email=f"owner_{rid}@sole.com",
            hashed_password="pw",
            role="owner",
            tenant_id=tid,
        )

        owner_token = create_access_token(user_id=owner_id, role="owner", tenant_id=tid)

        # Attempt to demote sole owner to editor
        resp = client.patch(
            f"/api/tenant/members/{owner_id}/role",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"role": "editor"},
        )
        assert resp.status_code == 400
        assert "sole organization owner" in resp.json()["detail"].lower()

    def test_owner_demotion_allowed_when_co_owner_exists(self):
        """Verify an owner can be demoted if another owner exists in the organization."""
        import uuid
        rid = uuid.uuid4().hex[:8]
        repo = get_repository()
        tid = f"tenant_multi_{rid}"
        owner1 = f"usr_co1_{rid}"
        owner2 = f"usr_co2_{rid}"

        repo.create_tenant(tid, "Multi Owner Org")
        repo.create_user(owner1, f"owner1_{rid}", f"o1_{rid}@multi.com", "pw", role="owner", tenant_id=tid)
        repo.create_user(owner2, f"owner2_{rid}", f"o2_{rid}@multi.com", "pw", role="owner", tenant_id=tid)

        owner1_token = create_access_token(user_id=owner1, role="owner", tenant_id=tid)

        # Owner 1 demotes themselves (allowed because owner 2 exists)
        resp = client.patch(
            f"/api/tenant/members/{owner1}/role",
            headers={"Authorization": f"Bearer {owner1_token}"},
            json={"role": "editor"},
        )
        assert resp.status_code == 200
        assert resp.json()["new_role"] == "editor"
        assert repo.get_user_by_id(owner1, tenant_id=tid)["role"] == "editor"

    def test_sole_owner_removal_is_prevented(self):
        """Verify the sole owner cannot be removed from the organization."""
        import uuid
        rid = uuid.uuid4().hex[:8]
        repo = get_repository()
        tid = f"tenant_rem_{rid}"
        owner_id = f"usr_sole_{rid}"
        admin_id = f"usr_admin_{rid}"

        repo.create_tenant(tid, "Remove Owner Org")
        repo.create_user(owner_id, f"sole_{rid}", f"rem_{rid}@sole.com", "pw", role="owner", tenant_id=tid)
        repo.create_user(admin_id, f"admin_{rid}", f"adm_{rid}@sole.com", "pw", role="admin", tenant_id=tid)

        admin_token = create_access_token(user_id=admin_id, role="admin", tenant_id=tid)

        # Admin attempts to remove the sole owner
        resp = client.delete(
            f"/api/tenant/members/{owner_id}",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code in (400, 403)

    def test_atomic_bulk_folder_access(self):
        """Verify bulk folder access assignment applies atomically across users and folders."""
        import uuid
        rid = uuid.uuid4().hex[:8]
        repo = get_repository()
        tid = f"tenant_bulk_{rid}"
        u1, u2 = f"usr_bulk_1_{rid}", f"usr_bulk_2_{rid}"
        f1, f2 = f"fld_bulk_1_{rid}", f"fld_bulk_2_{rid}"

        repo.create_tenant(tid, "Bulk Tenant")
        repo.create_user(u1, f"u1_{rid}", f"u1_{rid}@test.com", "pw", role="viewer", tenant_id=tid)
        repo.create_user(u2, f"u2_{rid}", f"u2_{rid}@test.com", "pw", role="viewer", tenant_id=tid)
        repo.create_folder(f1, tid, "Folder 1", created_by="admin")
        repo.create_folder(f2, tid, "Folder 2", created_by="admin")

        assigned_count = repo.bulk_set_folder_access(
            tenant_id=tid,
            folder_ids=[f1, f2],
            user_ids=[u1, u2],
            access_level="editor",
            granted_by="admin",
        )
        assert assigned_count == 4

        # Verify access resolution
        for fid in [f1, f2]:
            members = repo.get_folder_members(fid, tid)
            member_ids = [m["user_id"] for m in members]
            assert u1 in member_ids
            assert u2 in member_ids
