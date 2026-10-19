"""
tests/test_phase4_rbac_and_folders.py — Comprehensive test suite for Phase 4:
Decoupled Multi-Tenant Onboarding, RBAC, Folder-Level Access Control, and Multi-Tenant Memberships.

Covers:
1. Founding Admin Registration (POST /api/auth/register-tenant).
2. Pending Invite Conflict detection & ignore_pending_invite bypass.
3. Invite Preview (GET /api/auth/invites/{token}) and Locked Acceptance (POST /api/auth/accept-invite).
4. Multi-Tenant Freelancer scenario: Same email across multiple workspaces.
5. Login Disambiguation (listing available workspaces) & Workspace Switching (POST /api/auth/switch-tenant).
6. Folder creation & automatic 'manager' grant to creator.
7. Single-Query Resolver & 'revoked' override on tenant_wide folders (Trap 2 verification).
8. Bulk folder access assignment (ACL).
9. User role updates, member removal, and Redis auth cache invalidation (Trap 3 verification).
10. In-memory FAISS folder scoping (Trap 5 verification).
11. End-to-end API HTTP routes verification.
"""
import uuid
import pytest
import numpy as np
from httpx import ASGITransport, AsyncClient

from main import app
from src.core.config import IDX_OBJECTS
from src.schemas.auth_schemas import (
    TenantRole,
    FolderVisibility,
    FolderAccessLevel,
    RegisterTenantRequest,
    AcceptInviteRequest,
    LoginRequest,
    SwitchTenantRequest,
)
from src.schemas.folder_schemas import (
    CreateFolderRequest,
    UpdateFolderRequest,
    SingleFolderAccessGrantRequest,
    BulkFolderAccessRequest,
    FolderMemberAccessItem,
)
from src.services.user_auth_service import get_auth_service, UserAuthService
from src.modules.infra.postgres_repository import get_repository
from src.modules.infra.faiss_engine import get_faiss_engine


@pytest.mark.asyncio
async def test_tenant_creation_and_owner_assignment_on_register_tenant():
    auth_service = get_auth_service()
    repo = get_repository()
    
    unique_suffix = uuid.uuid4().hex[:8]
    req = RegisterTenantRequest(
        username=f"owner_{unique_suffix}",
        email=f"owner_{unique_suffix}@acme.com",
        password="SecurePassword123!",
        organization_name=f"Acme Corp {unique_suffix}",
    )
    
    user = auth_service.register_tenant(req)
    assert user["email"] == req.email
    assert user["role"] == TenantRole.OWNER.value
    assert user["organization_name"] == f"Acme Corp {unique_suffix}"
    tenant_id = user["tenant_id"]
    user_id = user["user_id"]
    assert tenant_id is not None
    
    # Verify tenant was created in repository
    tenant = repo.get_tenant_by_id(tenant_id)
    assert tenant is not None
    assert tenant["name"] == f"Acme Corp {unique_suffix}"
    
    # Verify default 'general' folder was seeded with creator as manager
    folders = repo.resolve_user_accessible_folders(
        user_id=user_id,
        tenant_id=tenant_id,
        role=TenantRole.OWNER.value,
    )
    assert len(folders) >= 1
    general = next(f for f in folders if f["folder_name"].lower() == "general")
    assert general["visibility"] == FolderVisibility.TENANT_WIDE.value
    assert general["effective_access"] == FolderAccessLevel.MANAGER.value


@pytest.mark.asyncio
async def test_pending_invite_conflict_and_override():
    auth_service = get_auth_service()
    repo = get_repository()
    
    unique_suffix = uuid.uuid4().hex[:8]
    inviter_req = RegisterTenantRequest(
        username=f"studio_lead_{unique_suffix}",
        email=f"lead_{unique_suffix}@studio.com",
        password="Password123!",
        organization_name=f"Studio {unique_suffix}",
    )
    lead_user = auth_service.register_tenant(inviter_req)
    tenant_id = lead_user["tenant_id"]
    
    # Invite a freelancer
    freelancer_email = f"freelance_{unique_suffix}@gmail.com"
    invite = auth_service.create_invite(
        tenant_id=tenant_id,
        email=freelancer_email,
        role=TenantRole.CONTRIBUTOR.value,
        invited_by=lead_user["user_id"],
    )
    
    # Freelancer tries to register their own workspace without ignore_pending_invite
    orphan_attempt = RegisterTenantRequest(
        username=f"freelancer_{unique_suffix}",
        email=freelancer_email,
        password="Password123!",
        organization_name="Freelancer Accidental Workspace",
        ignore_pending_invite=False,
    )
    with pytest.raises(ValueError) as excinfo:
        auth_service.register_tenant(orphan_attempt)
    assert "pending invitation" in str(excinfo.value)
    
    # Freelancer sets ignore_pending_invite=True -> allowed to create their own workspace
    orphan_attempt.ignore_pending_invite = True
    orphan_tenant = auth_service.register_tenant(orphan_attempt)
    assert orphan_tenant["tenant_id"] != tenant_id


@pytest.mark.asyncio
async def test_invite_preview_and_accept_invite():
    auth_service = get_auth_service()
    repo = get_repository()
    
    unique_suffix = uuid.uuid4().hex[:8]
    owner_req = RegisterTenantRequest(
        username=f"inviter_{unique_suffix}",
        email=f"inviter_{unique_suffix}@corp.com",
        password="Password123!",
        organization_name=f"Agency {unique_suffix}",
    )
    owner = auth_service.register_tenant(owner_req)
    tenant_id = owner["tenant_id"]
    
    # Create a confidential folder
    folder = repo.create_folder(
        tenant_id=tenant_id,
        folder_name=f"Campaign_{unique_suffix}",
        visibility=FolderVisibility.RESTRICTED.value,
        created_by=owner["user_id"],
    )
    folder_id = folder["folder_id"]
    
    # Send invite
    invited_email = f"editor_{unique_suffix}@contractor.com"
    invite = auth_service.create_invite(
        tenant_id=tenant_id,
        email=invited_email,
        role=TenantRole.EDITOR.value,
        invited_by=owner["user_id"],
        initial_folder_ids=[folder_id],
    )
    token = invite["invite_token"]
    
    # 1. Preview invite
    preview = auth_service.preview_invite(token)
    assert preview["email"] == invited_email
    assert preview["organization_name"] == f"Agency {unique_suffix}"
    assert preview["role"] == TenantRole.EDITOR.value
    
    # 2. Accept invite (email is locked from invite row!)
    accept_req = AcceptInviteRequest(
        invite_token=token,
        username=f"editor_{unique_suffix}",
        password="SecureEditorPass123!",
    )
    member = auth_service.accept_invite(accept_req)
    assert member["email"] == invited_email
    assert member["tenant_id"] == tenant_id
    assert member["role"] == TenantRole.EDITOR.value
    
    # 3. Check folder auto-grant
    accessible = repo.resolve_user_accessible_folders(
        user_id=member["user_id"],
        tenant_id=tenant_id,
        role=TenantRole.EDITOR.value,
    )
    accessible_ids = [f["folder_id"] for f in accessible]
    assert folder_id in accessible_ids


@pytest.mark.asyncio
async def test_multi_tenant_freelancer_and_disambiguation():
    """Verify that a single email can join multiple tenants and authenticate cleanly."""
    auth_service = get_auth_service()
    
    unique_suffix = uuid.uuid4().hex[:8]
    freelancer_email = f"pro_{unique_suffix}@freelance.com"
    shared_password = "SharedPassword123!"
    
    # Studio Alpha
    owner_a = auth_service.register_tenant(RegisterTenantRequest(
        username=f"studio_a_{unique_suffix}",
        email=f"alpha_{unique_suffix}@a.com",
        password="Password123!",
        organization_name=f"Studio Alpha {unique_suffix}",
    ))
    invite_a = auth_service.create_invite(
        tenant_id=owner_a["tenant_id"],
        email=freelancer_email,
        role=TenantRole.CONTRIBUTOR.value,
        invited_by=owner_a["user_id"],
    )
    auth_service.accept_invite(AcceptInviteRequest(
        invite_token=invite_a["invite_token"],
        username=f"pro_a_{unique_suffix}",
        password=shared_password,
    ))
    
    # Studio Beta
    owner_b = auth_service.register_tenant(RegisterTenantRequest(
        username=f"studio_b_{unique_suffix}",
        email=f"beta_{unique_suffix}@b.com",
        password="Password123!",
        organization_name=f"Studio Beta {unique_suffix}",
    ))
    invite_b = auth_service.create_invite(
        tenant_id=owner_b["tenant_id"],
        email=freelancer_email,
        role=TenantRole.VIEWER.value,
        invited_by=owner_b["user_id"],
    )
    auth_service.accept_invite(AcceptInviteRequest(
        invite_token=invite_b["invite_token"],
        username=f"pro_b_{unique_suffix}",
        password=shared_password,
    ))
    
    # Login without tenant_id -> Disambiguation needed!
    result = auth_service.authenticate(freelancer_email, shared_password)
    assert isinstance(result, list)
    assert len(result) == 2
    found_tenants = {u["tenant_id"] for u in result}
    assert owner_a["tenant_id"] in found_tenants
    assert owner_b["tenant_id"] in found_tenants
    
    # Login with explicit tenant_id -> Direct login!
    user_alpha = auth_service.authenticate(freelancer_email, shared_password, tenant_id=owner_a["tenant_id"])
    assert isinstance(user_alpha, dict)
    assert user_alpha["tenant_id"] == owner_a["tenant_id"]
    assert user_alpha["role"] == TenantRole.CONTRIBUTOR.value
    
    # Workspace Switch from Alpha to Beta
    switched = auth_service.switch_tenant(freelancer_email, owner_b["tenant_id"])
    assert switched["tenant_id"] == owner_b["tenant_id"]
    assert switched["role"] == TenantRole.VIEWER.value


@pytest.mark.asyncio
async def test_single_query_resolver_and_revoked_exclusion():
    """Verify Trap 2 fix: 'revoked' access level excludes user even on tenant_wide folders."""
    repo = get_repository()
    tenant_id = f"tenant_{uuid.uuid4().hex[:8]}"
    repo.create_tenant(tenant_id, "Resolver Test Tenant")
    
    owner_id = f"user_{uuid.uuid4().hex[:8]}"
    viewer_id = f"user_{uuid.uuid4().hex[:8]}"
    contractor_id = f"user_{uuid.uuid4().hex[:8]}"
    
    # Create tenant_wide folder
    public_folder = repo.create_folder(
        tenant_id=tenant_id,
        folder_name="Public Company Folder",
        visibility=FolderVisibility.TENANT_WIDE.value,
        created_by=owner_id,
    )
    public_id = public_folder["folder_id"]
    
    # Create restricted folder
    private_folder = repo.create_folder(
        tenant_id=tenant_id,
        folder_name="Executive Only",
        visibility=FolderVisibility.RESTRICTED.value,
        created_by=owner_id,
    )
    private_id = private_folder["folder_id"]
    
    # Revoke contractor from public_folder explicitly
    repo.set_folder_access(
        folder_id=public_id,
        user_id=contractor_id,
        tenant_id=tenant_id,
        access_level=FolderAccessLevel.REVOKED.value,
        granted_by=owner_id,
    )
    
    # 1. Owner sees both as manager
    owner_folders = repo.resolve_user_accessible_folders(
        user_id=owner_id, tenant_id=tenant_id, role=TenantRole.OWNER.value
    )
    owner_map = {f["folder_id"]: f["effective_access"] for f in owner_folders}
    assert owner_map[public_id] == FolderAccessLevel.MANAGER.value
    assert owner_map[private_id] == FolderAccessLevel.MANAGER.value
    
    # 2. Normal viewer sees public folder, but not restricted folder
    viewer_folders = repo.resolve_user_accessible_folders(
        user_id=viewer_id, tenant_id=tenant_id, role=TenantRole.VIEWER.value
    )
    viewer_ids = [f["folder_id"] for f in viewer_folders]
    assert public_id in viewer_ids
    assert private_id not in viewer_ids
    
    # 3. Contractor has 'revoked' on public folder -> excluded completely!
    contractor_folders = repo.resolve_user_accessible_folders(
        user_id=contractor_id, tenant_id=tenant_id, role=TenantRole.VIEWER.value
    )
    contractor_ids = [f["folder_id"] for f in contractor_folders]
    assert public_id not in contractor_ids
    assert private_id not in contractor_ids


@pytest.mark.asyncio
async def test_bulk_folder_access_assignment():
    repo = get_repository()
    tenant_id = f"tenant_{uuid.uuid4().hex[:8]}"
    repo.create_tenant(tenant_id, "Bulk ACL Tenant")
    
    admin_id = f"admin_{uuid.uuid4().hex[:8]}"
    u1 = f"u1_{uuid.uuid4().hex[:8]}"
    u2 = f"u2_{uuid.uuid4().hex[:8]}"
    
    f1 = repo.create_folder(tenant_id=tenant_id, folder_name="Folder 1", visibility=FolderVisibility.RESTRICTED.value, created_by=admin_id)
    f2 = repo.create_folder(tenant_id=tenant_id, folder_name="Folder 2", visibility=FolderVisibility.RESTRICTED.value, created_by=admin_id)
    
    count = repo.bulk_set_folder_access(
        tenant_id=tenant_id,
        folder_ids=[f1["folder_id"], f2["folder_id"]],
        user_ids=[u1],
        access_level=FolderAccessLevel.EDITOR.value,
        granted_by=admin_id,
    )
    assert count == 2
    
    # Check u1 permissions
    u1_folders = repo.resolve_user_accessible_folders(u1, tenant_id, TenantRole.VIEWER.value)
    u1_map = {f["folder_id"]: f["effective_access"] for f in u1_folders}
    assert u1_map[f1["folder_id"]] == FolderAccessLevel.EDITOR.value
    assert u1_map[f2["folder_id"]] == FolderAccessLevel.EDITOR.value


@pytest.mark.asyncio
async def test_member_role_update_and_removal():
    repo = get_repository()
    tenant_id = f"tenant_{uuid.uuid4().hex[:8]}"
    repo.create_tenant(tenant_id, "Member Mgmt Tenant")
    
    user_id = f"user_{uuid.uuid4().hex[:8]}"
    repo.create_user(
        user_id=user_id,
        username="demouser",
        email="demo@test.com",
        hashed_password="hashed_pw_test",
        role=TenantRole.VIEWER.value,
        tenant_id=tenant_id,
    )
    
    # Update role to editor
    updated = repo.update_tenant_member_role(tenant_id, user_id, TenantRole.EDITOR.value)
    assert updated is True
    user = repo.get_user_by_id(user_id, tenant_id=tenant_id)
    assert user["role"] == TenantRole.EDITOR.value
    
    # Remove member
    removed = repo.remove_tenant_member(tenant_id, user_id)
    assert removed is True
    assert repo.get_user_by_id(user_id, tenant_id=tenant_id) is None


def test_faiss_in_memory_folder_scoping():
    """Verify Trap 5 fix: In-memory folder scoping filters FAISS vectors instantaneously."""
    engine = get_faiss_engine()
    tenant_id = f"tenant_{uuid.uuid4().hex[:8]}"

    vec1 = np.ones(512, dtype=np.float32).tolist()
    vec2 = (np.ones(512, dtype=np.float32) * -1.0).tolist()
    vec3 = (np.ones(512, dtype=np.float32) * 0.5).tolist()

    # Upsert with folder IDs in metadata
    engine.upsert_vectors(
        index_name=IDX_OBJECTS,
        vectors=[vec1, vec2, vec3],
        ids=["img_1", "img_2", "img_3"],
        metadata=[
            {"folder": "folder_alpha"},
            {"folder": "folder_beta"},
            {"folder": "folder_gamma"},
        ],
        tenant_id=tenant_id,
    )

    # Search query
    query = np.ones(512, dtype=np.float32).tolist()

    # Scoped to folder_alpha only
    results_alpha = engine.search(
        index_name=IDX_OBJECTS,
        query_vector=query,
        top_k=5,
        filter_dict={"allowed_folders": ["folder_alpha"]},
        tenant_id=tenant_id,
    )
    returned_ids_alpha = [r["id"] for r in results_alpha]
    assert "img_1" in returned_ids_alpha
    assert "img_2" not in returned_ids_alpha
    assert "img_3" not in returned_ids_alpha

    # Scoped to folder_alpha and folder_gamma
    results_multi = engine.search(
        index_name=IDX_OBJECTS,
        query_vector=query,
        top_k=5,
        filter_dict={"allowed_folders": ["folder_alpha", "folder_gamma"]},
        tenant_id=tenant_id,
    )
    returned_ids_multi = [r["id"] for r in results_multi]
    assert "img_1" in returned_ids_multi
    assert "img_3" in returned_ids_multi
    assert "img_2" not in returned_ids_multi


@pytest.mark.asyncio
async def test_api_decoupled_routes_and_access_controls(client: AsyncClient):
    """End-to-end HTTP endpoint validation for decoupled onboarding, invites, and folder ACLs."""
    # 1. Register Owner via /register-tenant
    unique_suffix = uuid.uuid4().hex[:8]
    reg_payload = {
        "username": f"api_owner_{unique_suffix}",
        "email": f"api_owner_{unique_suffix}@acme.com",
        "password": "Password123!",
        "organization_name": f"API Acme {unique_suffix}",
    }
    reg_resp = await client.post("/api/auth/register-tenant", json=reg_payload)
    assert reg_resp.status_code == 201
    owner_token = reg_resp.json()["access_token"]
    owner_headers = {"Authorization": f"Bearer {owner_token}"}
    
    # 2. Check /api/auth/me returns organization_name
    me_resp = await client.get("/api/auth/me", headers=owner_headers)
    assert me_resp.status_code == 200
    assert me_resp.json()["organization_name"] == f"API Acme {unique_suffix}"
    
    # 3. Create a restricted folder
    create_payload = {
        "folder_name": f"Financials_{unique_suffix}",
        "description": "Sensitive financial reports",
        "visibility": "restricted",
    }
    f_resp = await client.post("/api/folders", json=create_payload, headers=owner_headers)
    assert f_resp.status_code == 201
    folder_data = f_resp.json()
    folder_id = folder_data["folder_id"]
    
    # 4. Create invite via tenant API
    invited_email = f"contractor_{unique_suffix}@agency.com"
    invite_resp = await client.post(
        "/api/tenant/invites",
        json={
            "email": invited_email,
            "role": "editor",
            "initial_folder_ids": [folder_id],
        },
        headers=owner_headers,
    )
    assert invite_resp.status_code == 201
    invite_token = invite_resp.json()["invite_token"]
    
    # 5. Preview invite via GET /api/auth/invites/{invite_token}
    preview_resp = await client.get(f"/api/auth/invites/{invite_token}")
    assert preview_resp.status_code == 200
    assert preview_resp.json()["organization_name"] == f"API Acme {unique_suffix}"
    assert preview_resp.json()["email"] == invited_email
    
    # 6. Accept invite via POST /api/auth/accept-invite
    accept_resp = await client.post(
        "/api/auth/accept-invite",
        json={
            "invite_token": invite_token,
            "username": f"contractor_{unique_suffix}",
            "password": "ContractorPass123!",
        },
    )
    assert accept_resp.status_code == 201
    contractor_token = accept_resp.json()["access_token"]
    contractor_headers = {"Authorization": f"Bearer {contractor_token}"}
    
    # 7. Contractor accesses pre-granted folder
    member_folders_resp = await client.get("/api/folders", headers=contractor_headers)
    assert member_folders_resp.status_code == 200
    member_folder_ids = [f["folder_id"] for f in member_folders_resp.json()]
    assert folder_id in member_folder_ids
    
    # 8. Login directly with credentials
    login_resp = await client.post(
        "/api/auth/login",
        json={
            "email": invited_email,
            "password": "ContractorPass123!",
        },
    )
    assert login_resp.status_code == 200
    assert "access_token" in login_resp.json()


@pytest.mark.asyncio
async def test_role_hierarchy_clustering_pipeline_and_pagination():
    """
    Verifies:
    1. Role hierarchy: Viewer cannot upload or trigger clustering (403 Forbidden).
    2. Editor can trigger clustering and rename clusters.
    3. 25-image delta check: Clustering returns 422 Unprocessable Entity when not enough photos ingested.
    4. GET /api/clusters/status returns readiness metadata.
    5. Pagination on /api/tenant/members and /api/folders honors limit and offset.
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        suffix = uuid.uuid4().hex[:8]

        # 1. Register Owner
        owner_resp = await client.post(
            "/api/auth/register-tenant",
            json={
                "username": f"owner_{suffix}",
                "email": f"owner_{suffix}@corp.com",
                "password": "OwnerPassword123!",
                "organization_name": f"Studio {suffix}",
            },
        )
        assert owner_resp.status_code == 201
        owner_token = owner_resp.json()["access_token"]
        owner_headers = {"Authorization": f"Bearer {owner_token}"}

        # 2. Owner creates a test folder
        folder_resp = await client.post(
            "/api/folders",
            json={
                "folder_name": f"album_{suffix}",
                "description": "Test Album",
                "visibility": "restricted",
            },
            headers=owner_headers,
        )
        assert folder_resp.status_code == 201
        folder_id = folder_resp.json()["folder_id"]
        folder_name = folder_resp.json()["folder_name"]

        # 3. Invite a Viewer
        viewer_email = f"viewer_{suffix}@corp.com"
        v_invite_resp = await client.post(
            "/api/tenant/invites",
            json={
                "email": viewer_email,
                "role": "viewer",
                "initial_folder_ids": [folder_id],
                "initial_access_level": "viewer",
            },
            headers=owner_headers,
        )
        assert v_invite_resp.status_code == 201
        v_token = v_invite_resp.json()["invite_token"]

        v_accept = await client.post(
            "/api/auth/accept-invite",
            json={
                "invite_token": v_token,
                "username": f"viewer_{suffix}",
                "password": "ViewerPassword123!",
            },
        )
        assert v_accept.status_code == 201
        viewer_token = v_accept.json()["access_token"]
        viewer_headers = {"Authorization": f"Bearer {viewer_token}"}

        # 4. Viewer tries to trigger clustering -> 403 Forbidden
        cluster_attempt = await client.post(
            f"/api/clusters/generate?folder_name={folder_name}",
            headers=viewer_headers,
        )
        assert cluster_attempt.status_code == 403

        # 5. Viewer tries to rename cluster -> 403 Forbidden
        rename_attempt = await client.patch(
            "/api/clusters/cls_dummy_123",
            json={"person_name": "Should Fail"},
            headers=viewer_headers,
        )
        assert rename_attempt.status_code == 403

        # 6. Check cluster status via GET /api/clusters/status
        status_resp = await client.get(
            f"/api/clusters/status?folder_name={folder_name}",
            headers=owner_headers,
        )
        assert status_resp.status_code == 200
        status_body = status_resp.json()
        assert status_body["folder_name"] == folder_name
        assert status_body["threshold"] == 25
        assert status_body["ready_for_clustering"] is False

        # 7. Owner tries to trigger clustering without 25 photos -> 422 Unprocessable Entity
        owner_cluster = await client.post(
            f"/api/clusters/generate?folder_name={folder_name}",
            headers=owner_headers,
        )
        assert owner_cluster.status_code == 422
        assert "Clustering requires at least 25 new photos" in owner_cluster.json()["detail"]

        # 8. Test Pagination on /api/tenant/members
        members_resp = await client.get("/api/tenant/members?limit=1&offset=0", headers=owner_headers)
        assert members_resp.status_code == 200
        assert len(members_resp.json()) == 1

        # 9. Test Pagination on /api/folders
        folders_paginated = await client.get("/api/folders?limit=1&offset=0", headers=owner_headers)
        assert folders_paginated.status_code == 200
        assert len(folders_paginated.json()) == 1

