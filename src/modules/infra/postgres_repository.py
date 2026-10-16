"""
src/modules/infra/postgres_repository.py — Production PostgreSQL Repository with Row-Level Security (RLS).
Replaces legacy SQLite with PostgreSQL async connection pooling (asyncpg) and kernel-level tenant isolation.
Provides zero-dependency in-memory fallback for local offline unit testing when PostgreSQL is not running.
"""
import asyncio
import json
import logging
import os
import threading
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, AsyncGenerator, Dict, List, Optional, Tuple

from src.core.tenant_context import get_current_tenant_id

logger = logging.getLogger("src.modules.infra.postgres_repository")

# Check for asyncpg availability
try:
    import asyncpg
    HAS_ASYNCPG = True
except ImportError:
    HAS_ASYNCPG = False
    logger.warning("asyncpg not installed; PostgreSQL operations will use in-memory testing store until installed.")

POSTGRES_POOL: Optional[Any] = None
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()


def is_postgres_configured() -> bool:
    """Check if PostgreSQL database URL is configured and driver is present."""
    return bool(DATABASE_URL and HAS_ASYNCPG and ("postgres" in DATABASE_URL or "postgresql" in DATABASE_URL))


async def get_postgres_pool() -> Optional[Any]:
    """Retrieve or initialize the global asyncpg connection pool."""
    global POSTGRES_POOL
    if not is_postgres_configured():
        return None

    if POSTGRES_POOL is None:
        try:
            url = DATABASE_URL
            if url.startswith("postgresql+asyncpg://"):
                url = url.replace("postgresql+asyncpg://", "postgresql://", 1)

            POSTGRES_POOL = await asyncpg.create_pool(
                url,
                min_size=int(os.getenv("PG_POOL_MIN", "5")),
                max_size=int(os.getenv("PG_POOL_MAX", "20")),
                timeout=float(os.getenv("PG_TIMEOUT", "30.0")),
            )
            logger.info("Successfully connected to PostgreSQL connection pool")
            await init_postgres_tables()
        except Exception as e:
            logger.warning("Failed to connect to PostgreSQL (%s); running in in-memory test mode.", e)
            POSTGRES_POOL = None

    return POSTGRES_POOL


@asynccontextmanager
async def get_tenant_connection(tenant_id: str) -> AsyncGenerator[Any, None]:
    """
    Acquire a connection from the pool and enforce PostgreSQL Row-Level Security (RLS)
    by setting 'app.current_tenant_id' inside the transaction session.
    """
    pool = await get_postgres_pool()
    if not pool:
        raise RuntimeError("PostgreSQL connection pool is not available")

    async with pool.acquire() as conn:
        async with conn.transaction():
            clean_tid = (tenant_id or get_current_tenant_id()).strip()
            await conn.execute("SELECT set_config('app.current_tenant_id', $1, true)", clean_tid)
            yield conn


@asynccontextmanager
async def get_bypass_rls_connection() -> AsyncGenerator[Any, None]:
    """
    Acquire a connection from the pool and bypass PostgreSQL Row-Level Security (RLS)
    strictly for pre-auth lookup (login by email, invite token lookup).
    """
    pool = await get_postgres_pool()
    if not pool:
        raise RuntimeError("PostgreSQL connection pool is not available")

    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("SELECT set_config('app.bypass_rls', 'on', true)")
            yield conn


async def init_postgres_tables() -> None:
    """Initialize PostgreSQL tables, composite indexes, triggers, and RLS policies."""
    pool = await get_postgres_pool()
    if not pool:
        return

    async with pool.acquire() as conn:
        async with conn.transaction():
            # 1. Base Tables
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS tenants (
                    tenant_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    storage_bucket TEXT,
                    is_active BOOLEAN NOT NULL DEFAULT TRUE,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
                ALTER TABLE tenants ADD COLUMN IF NOT EXISTS storage_bucket TEXT;
                ALTER TABLE tenants ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT TRUE;
                ALTER TABLE tenants ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW();

                CREATE TABLE IF NOT EXISTS users (
                    user_id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL DEFAULT 'default',
                    username TEXT,
                    email TEXT,
                    hashed_password TEXT,
                    role TEXT DEFAULT 'viewer',
                    storage_bucket TEXT,
                    is_active BOOLEAN NOT NULL DEFAULT TRUE,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    last_seen TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
                ALTER TABLE users ADD COLUMN IF NOT EXISTS storage_bucket TEXT;
                ALTER TABLE users ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT TRUE;
                ALTER TABLE users DROP CONSTRAINT IF EXISTS uq_global_email;
                ALTER TABLE users DROP CONSTRAINT IF EXISTS uq_users_email;
                ALTER TABLE users DROP CONSTRAINT IF EXISTS users_email_key;
                DO $$ BEGIN
                    ALTER TABLE users ADD CONSTRAINT uq_tenant_email UNIQUE (tenant_id, email);
                EXCEPTION WHEN duplicate_table OR duplicate_object THEN NULL; END $$;
                DO $$ BEGIN
                    ALTER TABLE users ADD CONSTRAINT uq_tenant_username UNIQUE (tenant_id, username);
                EXCEPTION WHEN duplicate_table OR duplicate_object THEN NULL; END $$;
                CREATE INDEX IF NOT EXISTS idx_pg_users_tenant ON users(tenant_id);
                CREATE INDEX IF NOT EXISTS idx_pg_users_email ON users(tenant_id, email);
                CREATE INDEX IF NOT EXISTS idx_pg_users_email_global ON users(LOWER(email)) WHERE is_active = TRUE;
                CREATE INDEX IF NOT EXISTS idx_pg_users_role ON users(tenant_id, role);

                CREATE TABLE IF NOT EXISTS folders (
                    folder_id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    folder_name TEXT NOT NULL,
                    description TEXT,
                    visibility TEXT NOT NULL DEFAULT 'restricted',
                    photo_count INT NOT NULL DEFAULT 0,
                    created_by TEXT,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    CONSTRAINT uq_tenant_folder_name UNIQUE (tenant_id, folder_name)
                );
                CREATE INDEX IF NOT EXISTS idx_pg_folders_tenant_vis ON folders(tenant_id, visibility);
                CREATE INDEX IF NOT EXISTS idx_pg_folders_tenant_name ON folders(tenant_id, folder_name);

                CREATE TABLE IF NOT EXISTS folder_user_access (
                    folder_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    tenant_id TEXT NOT NULL,
                    access_level TEXT NOT NULL DEFAULT 'inherit',
                    granted_by TEXT,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    PRIMARY KEY (folder_id, user_id)
                );
                CREATE INDEX IF NOT EXISTS idx_pg_fua_lookup ON folder_user_access(tenant_id, user_id, folder_id);

                CREATE TABLE IF NOT EXISTS tenant_invites (
                    invite_id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    email TEXT NOT NULL,
                    role TEXT NOT NULL DEFAULT 'viewer',
                    initial_folder_ids TEXT[] NOT NULL DEFAULT '{}',
                    initial_access_level TEXT NOT NULL DEFAULT 'inherit',
                    invited_by TEXT,
                    invite_token TEXT UNIQUE NOT NULL,
                    expires_at TIMESTAMPTZ NOT NULL,
                    accepted_at TIMESTAMPTZ,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
                CREATE INDEX IF NOT EXISTS idx_pg_invites_token ON tenant_invites(invite_token);
                CREATE INDEX IF NOT EXISTS idx_pg_invites_tenant_email ON tenant_invites(tenant_id, email);

                CREATE TABLE IF NOT EXISTS photos (
                    image_id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    folder_id TEXT NOT NULL,
                    storage_key TEXT NOT NULL,
                    filename TEXT NOT NULL,
                    uploaded_by TEXT,
                    faiss_id BIGINT UNIQUE,
                    metadata JSONB DEFAULT '{}'::jsonb,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
                CREATE INDEX IF NOT EXISTS idx_pg_photos_tenant_folder ON photos(tenant_id, folder_id);
                CREATE INDEX IF NOT EXISTS idx_pg_photos_faiss ON photos(tenant_id, faiss_id);

                CREATE TABLE IF NOT EXISTS upload_jobs (
                    job_id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL DEFAULT 'default',
                    user_id TEXT NOT NULL,
                    folder TEXT NOT NULL,
                    status TEXT NOT NULL,
                    total_files INT DEFAULT 0,
                    processed_files INT DEFAULT 0,
                    payload JSONB,
                    logs JSONB DEFAULT '[]'::jsonb,
                    result JSONB,
                    error TEXT,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
                CREATE INDEX IF NOT EXISTS idx_pg_jobs_tenant ON upload_jobs(tenant_id);

                CREATE TABLE IF NOT EXISTS face_clusters (
                    cluster_id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL DEFAULT 'default',
                    user_id TEXT NOT NULL,
                    folder TEXT,
                    person_name TEXT,
                    representative_face_url TEXT,
                    face_count INT DEFAULT 0,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
                CREATE INDEX IF NOT EXISTS idx_pg_clusters_tenant ON face_clusters(tenant_id, folder);

                CREATE TABLE IF NOT EXISTS vector_metadata (
                    int_id BIGSERIAL PRIMARY KEY,
                    tenant_id TEXT NOT NULL DEFAULT 'default',
                    index_name TEXT NOT NULL,
                    vector_id TEXT NOT NULL,
                    url TEXT,
                    folder TEXT,
                    metadata_json JSONB NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
                CREATE UNIQUE INDEX IF NOT EXISTS idx_pg_vm_tenant_idx_vec ON vector_metadata(tenant_id, index_name, vector_id);
                CREATE INDEX IF NOT EXISTS idx_pg_vm_tenant_folder ON vector_metadata(tenant_id, folder);
                CREATE INDEX IF NOT EXISTS idx_pg_vm_tenant_url ON vector_metadata(tenant_id, url);
            """)

            # 2. Trigger for atomic folder photo count
            await conn.execute("""
                CREATE OR REPLACE FUNCTION update_folder_photo_count()
                RETURNS TRIGGER AS $$
                BEGIN
                    IF TG_OP = 'INSERT' THEN
                        UPDATE folders SET photo_count = photo_count + 1, updated_at = NOW() WHERE folder_id = NEW.folder_id;
                    ELSIF TG_OP = 'DELETE' THEN
                        UPDATE folders SET photo_count = GREATEST(0, photo_count - 1), updated_at = NOW() WHERE folder_id = OLD.folder_id;
                    END IF;
                    RETURN NULL;
                END;
                $$ LANGUAGE plpgsql;

                DROP TRIGGER IF EXISTS trg_photos_count ON photos;
                CREATE TRIGGER trg_photos_count
                AFTER INSERT OR DELETE ON photos
                FOR EACH ROW EXECUTE FUNCTION update_folder_photo_count();
            """)

            # 3. Apply Row-Level Security (RLS) Policies
            # Standard isolated tables
            standard_tables = [
                "vector_metadata", "face_clusters",
                "upload_jobs", "folders", "folder_user_access", "photos"
            ]
            for table in standard_tables:
                await conn.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;")
                await conn.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;")
                policy_name = f"tenant_isolation_{table}"
                await conn.execute(f"""
                    DO $$
                    BEGIN
                        IF NOT EXISTS (
                            SELECT 1 FROM pg_policies 
                            WHERE tablename = '{table}' AND policyname = '{policy_name}'
                        ) THEN
                            CREATE POLICY {policy_name} ON {table}
                                FOR ALL
                                USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''))
                                WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''));
                        END IF;
                    END
                    $$;
                """)

            # Pre-auth bypass tables (users, tenant_invites, tenants)
            bypass_tables = ["users", "tenant_invites", "tenants"]
            for table in bypass_tables:
                await conn.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;")
                await conn.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;")
                policy_name = f"tenant_bypass_isolation_{table}"
                await conn.execute(f"""
                    DO $$
                    BEGIN
                        IF NOT EXISTS (
                            SELECT 1 FROM pg_policies 
                            WHERE tablename = '{table}' AND policyname = '{policy_name}'
                        ) THEN
                            CREATE POLICY {policy_name} ON {table}
                                FOR ALL
                                USING (
                                    tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')
                                    OR current_setting('app.bypass_rls', true) = 'on'
                                )
                                WITH CHECK (
                                    tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')
                                    OR current_setting('app.bypass_rls', true) = 'on'
                                );
                        END IF;
                    END
                    $$;
                """)

            logger.info("PostgreSQL tables, triggers, and Row-Level Security policies active")


_bg_loop: Optional[asyncio.AbstractEventLoop] = None
_bg_thread: Optional[threading.Thread] = None
_bg_lock = threading.Lock()


def _get_bg_loop() -> asyncio.AbstractEventLoop:
    global _bg_loop, _bg_thread
    with _bg_lock:
        if _bg_loop is None or not _bg_loop.is_running():
            _bg_loop = asyncio.new_event_loop()
            _bg_thread = threading.Thread(target=_bg_loop.run_forever, daemon=True)
            _bg_thread.start()
        return _bg_loop


def _run_sync(coro):
    """Safely execute an asynchronous coroutine in the persistent background event loop."""
    loop = _get_bg_loop()
    future = asyncio.run_coroutine_threadsafe(coro, loop)
    return future.result()


# ===============================================================
# In-Memory Fallback State (Zero-dependency for unit testing)
# ===============================================================
_mem_lock = threading.RLock()
_mem_users: Dict[str, dict] = {}           # user_id -> dict
_mem_jobs: Dict[str, dict] = {}            # job_id -> dict
_mem_clusters: Dict[str, dict] = {}        # cluster_id -> dict
_mem_vector_metadata: Dict[int, dict] = {} # int_id -> dict
_mem_int_counter: int = 1

# Multi-Tenant & RBAC in-memory fallback state
_mem_tenants: Dict[str, dict] = {
    "default": {
        "tenant_id": "default",
        "name": "Default Organization",
        "storage_bucket": "visual-search-media",
        "is_active": True,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
}
_mem_folders: Dict[str, dict] = {
    "default": {
        "folder_id": "default",
        "tenant_id": "default",
        "folder_name": "general",
        "description": "Default general album",
        "visibility": "tenant_wide",
        "photo_count": 0,
        "created_by": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
}
_mem_folder_access: Dict[Tuple[str, str], dict] = {} # (folder_id, user_id) -> dict
_mem_invites: Dict[str, dict] = {}                  # invite_id / invite_token -> dict
_mem_photos: Dict[str, dict] = {}                   # image_id -> dict


# ===============================================================
# User Operations
# ===============================================================

async def get_or_create_anonymous_user(user_id: Optional[str] = None, tenant_id: Optional[str] = None) -> str:
    """Get existing or generate and persist anonymous user UUID."""
    uid = user_id.strip() if user_id else str(uuid.uuid4())
    tid = (tenant_id or get_current_tenant_id()).strip()
    pool = await get_postgres_pool()

    if pool:
        async with get_tenant_connection(tid) as conn:
            row = await conn.fetchrow("SELECT user_id FROM users WHERE user_id = $1", uid)
            if not row:
                now = datetime.now(timezone.utc)
                await conn.execute(
                    "INSERT INTO users (user_id, tenant_id, role, created_at, last_seen) VALUES ($1, $2, 'anonymous', $3, $3)",
                    uid, tid, now
                )
        return uid

    with _mem_lock:
        if uid not in _mem_users:
            now = datetime.now(timezone.utc).isoformat()
            _mem_users[uid] = {
                "user_id": uid,
                "tenant_id": tid,
                "role": "anonymous",
                "created_at": now,
                "last_seen": now,
            }
        return uid


async def get_user_by_id(user_id: str, tenant_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Retrieve user record by user_id."""
    tid = (tenant_id or get_current_tenant_id()).strip()
    pool = await get_postgres_pool()
    if pool:
        async with get_tenant_connection(tid) as conn:
            row = await conn.fetchrow("SELECT * FROM users WHERE user_id = $1", user_id)
            return dict(row) if row else None

    with _mem_lock:
        user = _mem_users.get(user_id)
        return dict(user) if user else None


# ===============================================================
# Job Operations
# ===============================================================

async def db_create_job(
    user_id: str,
    folder: str,
    total_files: int,
    payload: Optional[dict] = None,
    job_id: Optional[str] = None,
    tenant_id: Optional[str] = None,
) -> str:
    """Create a new tracking record for an upload batch scoped to tenant."""
    jid = job_id or str(uuid.uuid4())
    tid = (tenant_id or get_current_tenant_id()).strip()
    now_dt = datetime.now(timezone.utc)
    now_str = now_dt.isoformat()
    p_dict = payload or {}

    pool = await get_postgres_pool()
    if pool:
        async with get_tenant_connection(tid) as conn:
            await conn.execute(
                """
                INSERT INTO upload_jobs (
                    job_id, tenant_id, user_id, folder, status, total_files,
                    processed_files, payload, logs, created_at, updated_at
                ) VALUES ($1, $2, $3, $4, 'pending', $5, 0, $6, '[]'::jsonb, $7, $7)
                """,
                jid, tid, user_id, folder, total_files, json.dumps(p_dict), now_dt
            )
        return jid

    with _mem_lock:
        _mem_jobs[jid] = {
            "job_id": jid,
            "tenant_id": tid,
            "user_id": user_id,
            "folder": folder,
            "status": "pending",
            "total_files": total_files,
            "processed_files": 0,
            "payload": p_dict,
            "logs": [],
            "error": None,
            "created_at": now_str,
            "updated_at": now_str,
        }
        return jid


async def db_update_job(job_id: str, fields: dict, tenant_id: Optional[str] = None) -> None:
    """Update fields on a job record."""
    if not fields:
        return
    tid = (tenant_id or get_current_tenant_id()).strip()
    now_dt = datetime.now(timezone.utc)

    pool = await get_postgres_pool()
    if pool:
        async with get_tenant_connection(tid) as conn:
            set_clauses = []
            values = []
            idx = 1
            for k, v in fields.items():
                if k in ("payload", "logs", "result") and isinstance(v, (dict, list)):
                    v = json.dumps(v)
                set_clauses.append(f"{k} = ${idx}")
                values.append(v)
                idx += 1
            set_clauses.append(f"updated_at = ${idx}")
            values.append(now_dt)
            idx += 1
            values.append(job_id)
            query = f"UPDATE upload_jobs SET {', '.join(set_clauses)} WHERE job_id = ${idx}"
            await conn.execute(query, *values)
        return

    with _mem_lock:
        if job_id in _mem_jobs:
            _mem_jobs[job_id].update(fields)
            _mem_jobs[job_id]["updated_at"] = now_dt.isoformat()


async def db_get_job(job_id: str, tenant_id: Optional[str] = None) -> Optional[dict]:
    """Retrieve job details by job_id."""
    tid = (tenant_id or get_current_tenant_id()).strip()
    pool = await get_postgres_pool()
    if pool:
        async with get_tenant_connection(tid) as conn:
            row = await conn.fetchrow("SELECT * FROM upload_jobs WHERE job_id = $1", job_id)
        if not row:
            async with get_bypass_rls_connection() as bypass_conn:
                row = await bypass_conn.fetchrow("SELECT * FROM upload_jobs WHERE job_id = $1", job_id)
        if not row:
            return None
        res = dict(row)
        if isinstance(res.get("logs"), str):
            try:
                res["logs"] = json.loads(res["logs"])
            except Exception:
                res["logs"] = []
        elif res.get("logs") is None:
            res["logs"] = []
        return res

    with _mem_lock:
        job = _mem_jobs.get(job_id)
        return dict(job) if job else None


async def db_append_job_log(job_id: str, message: str, tenant_id: Optional[str] = None) -> None:
    """Append a log message to an upload job."""
    tid = (tenant_id or get_current_tenant_id()).strip()
    now_dt = datetime.now(timezone.utc)
    pool = await get_postgres_pool()
    if pool:
        async with get_tenant_connection(tid) as conn:
            row = await conn.fetchrow("SELECT logs FROM upload_jobs WHERE job_id = $1", job_id)
            current_logs = []
            if row and row["logs"]:
                current_logs = json.loads(row["logs"]) if isinstance(row["logs"], str) else list(row["logs"])
            current_logs.append(message)
            await conn.execute(
                "UPDATE upload_jobs SET logs = $1, updated_at = $2 WHERE job_id = $3",
                json.dumps(current_logs), now_dt, job_id
            )
        return

    with _mem_lock:
        if job_id in _mem_jobs:
            _mem_jobs[job_id].setdefault("logs", []).append(message)
            _mem_jobs[job_id]["updated_at"] = now_dt.isoformat()


# ===============================================================
# Face Cluster Operations
# ===============================================================

async def db_upsert_cluster(
    cluster_id: str,
    person_name: str,
    face_count: int,
    representative_face_url: Optional[str] = None,
    user_id: str = "system",
    folder: Optional[str] = None,
    tenant_id: Optional[str] = None,
) -> None:
    """Insert or update a face identity cluster."""
    tid = (tenant_id or get_current_tenant_id()).strip()
    now_dt = datetime.now(timezone.utc)
    rep_url = representative_face_url or ""

    pool = await get_postgres_pool()
    if pool:
        async with get_tenant_connection(tid) as conn:
            await conn.execute(
                """
                INSERT INTO face_clusters (cluster_id, tenant_id, user_id, folder, person_name, representative_face_url, face_count, updated_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                ON CONFLICT(cluster_id) DO UPDATE SET
                    tenant_id = EXCLUDED.tenant_id,
                    folder = EXCLUDED.folder,
                    person_name = EXCLUDED.person_name,
                    representative_face_url = EXCLUDED.representative_face_url,
                    face_count = EXCLUDED.face_count,
                    updated_at = EXCLUDED.updated_at
                """,
                cluster_id, tid, user_id, folder, person_name, rep_url, face_count, now_dt
            )
        return

    with _mem_lock:
        _mem_clusters[cluster_id] = {
            "cluster_id": cluster_id,
            "tenant_id": tid,
            "user_id": user_id,
            "folder": folder,
            "person_name": person_name,
            "representative_face_url": rep_url,
            "face_count": face_count,
            "updated_at": now_dt.isoformat(),
        }


async def db_rename_cluster(cluster_id: str, new_name: str, user_id: str, tenant_id: Optional[str] = None) -> bool:
    """Rename a face identity cluster."""
    tid = (tenant_id or get_current_tenant_id()).strip()
    now_dt = datetime.now(timezone.utc)
    pool = await get_postgres_pool()
    if pool:
        async with get_tenant_connection(tid) as conn:
            res = await conn.execute(
                "UPDATE face_clusters SET person_name = $1, updated_at = $2 WHERE cluster_id = $3",
                new_name, now_dt, cluster_id
            )
            return "UPDATE 1" in res

    with _mem_lock:
        cluster = _mem_clusters.get(cluster_id)
        if cluster and cluster.get("tenant_id") == tid:
            cluster["person_name"] = new_name
            cluster["updated_at"] = now_dt.isoformat()
            return True
        return False


# ===============================================================
# Vector Metadata Operations (Synchronous API for FAISS)
# ===============================================================

def sync_save_vector_metadata_batch(index_name: str, records: List[dict], tenant_id: Optional[str] = None) -> List[int]:
    """Insert or update metadata for a batch of vectors and return auto-increment integer IDs."""
    if not records:
        return []

    tid = (tenant_id or get_current_tenant_id()).strip()
    pool = _run_sync(get_postgres_pool()) if is_postgres_configured() else None

    if pool:
        async def _save():
            async with get_tenant_connection(tid) as conn:
                int_ids = []
                for rec in records:
                    vid = str(rec["id"])
                    url = rec.get("url") or rec.get("metadata", {}).get("url", "")
                    folder = rec.get("folder") or rec.get("metadata", {}).get("folder", "uncategorized")
                    meta_json = json.dumps(rec.get("metadata", {}))

                    row = await conn.fetchrow(
                        "SELECT int_id FROM vector_metadata WHERE index_name = $1 AND vector_id = $2",
                        index_name, vid
                    )
                    if row:
                        i_id = row["int_id"]
                        await conn.execute(
                            "UPDATE vector_metadata SET url = $1, folder = $2, metadata_json = $3 WHERE int_id = $4",
                            url, folder, meta_json, i_id
                        )
                    else:
                        row = await conn.fetchrow(
                            """
                            INSERT INTO vector_metadata (tenant_id, index_name, vector_id, url, folder, metadata_json)
                            VALUES ($1, $2, $3, $4, $5, $6)
                            RETURNING int_id
                            """,
                            tid, index_name, vid, url, folder, meta_json
                        )
                        i_id = row["int_id"]
                    int_ids.append(i_id)
                return int_ids

        return _run_sync(_save())

    global _mem_int_counter
    with _mem_lock:
        int_ids = []
        for rec in records:
            vid = str(rec["id"])
            existing_id = None
            for i_id, meta in _mem_vector_metadata.items():
                if meta.get("tenant_id") == tid and meta.get("index_name") == index_name and meta.get("vector_id") == vid:
                    existing_id = i_id
                    break

            if existing_id is not None:
                _mem_vector_metadata[existing_id].update({
                    "url": rec.get("url") or rec.get("metadata", {}).get("url", ""),
                    "folder": rec.get("folder") or rec.get("metadata", {}).get("folder", "uncategorized"),
                    "metadata": dict(rec.get("metadata", {})),
                })
                int_ids.append(existing_id)
            else:
                new_id = _mem_int_counter
                _mem_int_counter += 1
                _mem_vector_metadata[new_id] = {
                    "int_id": new_id,
                    "tenant_id": tid,
                    "index_name": index_name,
                    "vector_id": vid,
                    "url": rec.get("url") or rec.get("metadata", {}).get("url", ""),
                    "folder": rec.get("folder") or rec.get("metadata", {}).get("folder", "uncategorized"),
                    "metadata": dict(rec.get("metadata", {})),
                    "created_at": datetime.now(timezone.utc).isoformat(),
                }
                int_ids.append(new_id)
        return int_ids


def sync_get_vector_metadata_by_int_ids(index_name: str, int_ids: List[int], tenant_id: Optional[str] = None) -> Dict[int, dict]:
    """Fetch metadata dictionary keyed by int_id scoped to tenant."""
    if not int_ids:
        return {}

    tid = (tenant_id or get_current_tenant_id()).strip()
    pool = _run_sync(get_postgres_pool()) if is_postgres_configured() else None

    if pool:
        async def _get():
            async with get_tenant_connection(tid) as conn:
                rows = await conn.fetch(
                    "SELECT int_id, vector_id, url, folder, metadata_json FROM vector_metadata WHERE int_id = ANY($1) AND index_name = $2",
                    int_ids, index_name
                )
                lookup = {}
                for r in rows:
                    meta = json.loads(r["metadata_json"]) if isinstance(r["metadata_json"], str) else dict(r["metadata_json"])
                    lookup[int(r["int_id"])] = {
                        "id": r["vector_id"],
                        "url": r["url"],
                        "folder": r["folder"],
                        "metadata": meta,
                    }
                return lookup

        return _run_sync(_get())

    with _mem_lock:
        lookup = {}
        for i_id in int_ids:
            if i_id in _mem_vector_metadata:
                m = _mem_vector_metadata[i_id]
                if m.get("tenant_id") == tid and m.get("index_name") == index_name:
                    lookup[i_id] = {
                        "id": m["vector_id"],
                        "url": m["url"],
                        "folder": m["folder"],
                        "metadata": dict(m["metadata"]),
                    }
        return lookup


def sync_delete_vectors_by_ids(index_name: str, vector_ids: List[str], tenant_id: Optional[str] = None) -> List[int]:
    """Delete vectors by vector_ids scoped to tenant and return affected integer IDs."""
    if not vector_ids:
        return []

    tid = (tenant_id or get_current_tenant_id()).strip()
    pool = _run_sync(get_postgres_pool()) if is_postgres_configured() else None

    if pool:
        async def _delete():
            async with get_tenant_connection(tid) as conn:
                rows = await conn.fetch(
                    "SELECT int_id FROM vector_metadata WHERE index_name = $1 AND vector_id = ANY($2)",
                    index_name, vector_ids
                )
                int_ids = [r["int_id"] for r in rows]
                if int_ids:
                    await conn.execute("DELETE FROM vector_metadata WHERE int_id = ANY($1)", int_ids)
                return int_ids

        return _run_sync(_delete())

    with _mem_lock:
        to_delete = []
        for i_id, meta in _mem_vector_metadata.items():
            if meta.get("tenant_id") == tid and meta.get("index_name") == index_name and meta.get("vector_id") in vector_ids:
                to_delete.append(i_id)
        for i_id in to_delete:
            del _mem_vector_metadata[i_id]
        return to_delete


def sync_delete_vectors_by_url(url: str, tenant_id: Optional[str] = None) -> Dict[str, List[int]]:
    """Delete all vectors matching a specific image URL scoped to tenant."""
    tid = (tenant_id or get_current_tenant_id()).strip()
    pool = _run_sync(get_postgres_pool()) if is_postgres_configured() else None

    if pool:
        async def _delete():
            async with get_tenant_connection(tid) as conn:
                rows = await conn.fetch("SELECT int_id, index_name FROM vector_metadata WHERE url = $1", url)
                res: Dict[str, List[int]] = {}
                for r in rows:
                    res.setdefault(r["index_name"], []).append(r["int_id"])
                if rows:
                    await conn.execute("DELETE FROM vector_metadata WHERE url = $1", url)
                return res

        return _run_sync(_delete())

    with _mem_lock:
        res = {}
        to_del = []
        for i_id, m in _mem_vector_metadata.items():
            if m.get("tenant_id") == tid and m.get("url") == url:
                res.setdefault(m["index_name"], []).append(i_id)
                to_del.append(i_id)
        for i_id in to_del:
            del _mem_vector_metadata[i_id]
        return res


def sync_delete_vectors_by_folder(folder: str, tenant_id: Optional[str] = None) -> Dict[str, List[int]]:
    """Delete all vectors for a given folder scoped to tenant."""
    tid = (tenant_id or get_current_tenant_id()).strip()
    pool = _run_sync(get_postgres_pool()) if is_postgres_configured() else None

    if pool:
        async def _delete():
            async with get_tenant_connection(tid) as conn:
                rows = await conn.fetch("SELECT int_id, index_name FROM vector_metadata WHERE folder = $1", folder)
                res: Dict[str, List[int]] = {}
                for r in rows:
                    res.setdefault(r["index_name"], []).append(r["int_id"])
                if rows:
                    await conn.execute("DELETE FROM vector_metadata WHERE folder = $1", folder)
                return res

        return _run_sync(_delete())

    with _mem_lock:
        res = {}
        to_del = []
        for i_id, m in _mem_vector_metadata.items():
            if m.get("tenant_id") == tid and m.get("folder") == folder:
                res.setdefault(m["index_name"], []).append(i_id)
                to_del.append(i_id)
        for i_id in to_del:
            del _mem_vector_metadata[i_id]
        return res


def sync_get_folder_image_count(folder: str, tenant_id: Optional[str] = None) -> int:
    """Return count of distinct image URLs indexed for a folder scoped to tenant."""
    tid = (tenant_id or get_current_tenant_id()).strip()
    pool = _run_sync(get_postgres_pool()) if is_postgres_configured() else None

    if pool:
        async def _count():
            async with get_tenant_connection(tid) as conn:
                val = await conn.fetchval(
                    "SELECT COUNT(DISTINCT url) FROM vector_metadata WHERE folder = $1", folder
                )
                return int(val or 0)

        return _run_sync(_count())

    with _mem_lock:
        urls = {
            m["url"] for m in _mem_vector_metadata.values()
            if m.get("tenant_id") == tid and m.get("folder") == folder and m.get("url")
        }
        return len(urls)


def sync_list_all_indexed_folders(tenant_id: Optional[str] = None) -> List[str]:
    """List all folder names that have indexed vectors scoped to tenant."""
    tid = (tenant_id or get_current_tenant_id()).strip()
    pool = _run_sync(get_postgres_pool()) if is_postgres_configured() else None

    if pool:
        async def _list():
            async with get_tenant_connection(tid) as conn:
                rows = await conn.fetch(
                    "SELECT DISTINCT folder FROM vector_metadata WHERE folder IS NOT NULL ORDER BY folder"
                )
                return [r["folder"] for r in rows]

        return _run_sync(_list())

    with _mem_lock:
        folders = {
            m["folder"] for m in _mem_vector_metadata.values()
            if m.get("tenant_id") == tid and m.get("folder")
        }
        return sorted(list(folders))


def sync_get_all_vector_metadata(index_name: str, limit: int = 10000, tenant_id: Optional[str] = None) -> List[dict]:
    """Retrieve all vector metadata records for an index scoped to tenant."""
    tid = (tenant_id or get_current_tenant_id()).strip()
    pool = _run_sync(get_postgres_pool()) if is_postgres_configured() else None

    if pool:
        async def _all():
            async with get_tenant_connection(tid) as conn:
                rows = await conn.fetch(
                    "SELECT int_id, vector_id, url, folder, metadata_json, created_at FROM vector_metadata WHERE index_name = $1 LIMIT $2",
                    index_name, limit
                )
                res = []
                for r in rows:
                    meta = json.loads(r["metadata_json"]) if isinstance(r["metadata_json"], str) else dict(r["metadata_json"])
                    res.append({
                        "int_id": r["int_id"],
                        "id": r["vector_id"],
                        "url": r["url"],
                        "folder": r["folder"],
                        "metadata": meta,
                        "created_at": r["created_at"].isoformat() if hasattr(r["created_at"], "isoformat") else str(r["created_at"]),
                    })
                return res

        return _run_sync(_all())

    with _mem_lock:
        res = []
        for m in _mem_vector_metadata.values():
            if m.get("tenant_id") == tid and m.get("index_name") == index_name:
                res.append({
                    "int_id": m["int_id"],
                    "id": m["vector_id"],
                    "url": m["url"],
                    "folder": m["folder"],
                    "metadata": dict(m["metadata"]),
                    "created_at": m.get("created_at"),
                })
                if len(res) >= limit:
                    break
        return res


def sync_clear_vector_metadata(index_name: Optional[str] = None, tenant_id: Optional[str] = None) -> None:
    """Clear all vector metadata scoped to tenant."""
    tid = (tenant_id or get_current_tenant_id()).strip()
    pool = _run_sync(get_postgres_pool()) if is_postgres_configured() else None

    if pool:
        async def _clear():
            async with get_tenant_connection(tid) as conn:
                if index_name:
                    await conn.execute("DELETE FROM vector_metadata WHERE index_name = $1", index_name)
                else:
                    await conn.execute("DELETE FROM vector_metadata")

        _run_sync(_clear())
        return

    with _mem_lock:
        to_del = []
        for i_id, m in _mem_vector_metadata.items():
            if m.get("tenant_id") == tid:
                if index_name is None or m.get("index_name") == index_name:
                    to_del.append(i_id)
        for i_id in to_del:
            del _mem_vector_metadata[i_id]


# ===============================================================
# Unified PostgresRepository Class
# ===============================================================

class PostgresRepository:
    """Unified PostgreSQL repository instance implementing user, job, and cluster management."""

    def __init__(self):
        pass

    def get_user_by_id(self, user_id: str, tenant_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        return _run_sync(get_user_by_id(user_id, tenant_id=tenant_id))

    def create_user(
        self,
        user_id: str,
        username: str,
        email: str,
        hashed_password: str,
        role: str = "user",
        storage_bucket: Optional[str] = None,
        tenant_id: str = "default",
    ) -> bool:
        tid = (tenant_id or get_current_tenant_id()).strip()
        now_dt = datetime.now(timezone.utc)
        clean_email = email.strip().lower()
        pool = _run_sync(get_postgres_pool()) if is_postgres_configured() else None

        if pool:
            async def _create():
                try:
                    async with get_tenant_connection(tid) as conn:
                        await conn.execute(
                            """
                            INSERT INTO users (user_id, tenant_id, username, email, hashed_password, role, storage_bucket, created_at, last_seen)
                            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $8)
                            """,
                            user_id, tid, username.strip(), clean_email, hashed_password, role, storage_bucket, now_dt
                        )
                    return True
                except Exception as e:
                    logger.error("create_user failed: %s", e)
                    return False
            return _run_sync(_create())

        with _mem_lock:
            _mem_users[user_id] = {
                "user_id": user_id,
                "tenant_id": tid,
                "username": username.strip(),
                "email": clean_email,
                "hashed_password": hashed_password,
                "role": role,
                "storage_bucket": storage_bucket,
                "created_at": now_dt.isoformat(),
                "last_seen": now_dt.isoformat(),
            }
            return True

    def update_user_storage_bucket(self, user_id: str, storage_bucket: str, tenant_id: Optional[str] = None) -> bool:
        tid = (tenant_id or get_current_tenant_id()).strip()
        now_dt = datetime.now(timezone.utc)
        pool = _run_sync(get_postgres_pool()) if is_postgres_configured() else None

        if pool:
            async def _update():
                async with get_tenant_connection(tid) as conn:
                    res = await conn.execute(
                        "UPDATE users SET storage_bucket = $1, last_seen = $2 WHERE user_id = $3",
                        storage_bucket, now_dt, user_id
                    )
                    return "UPDATE 1" in res
            return _run_sync(_update())

        with _mem_lock:
            if user_id in _mem_users:
                _mem_users[user_id]["storage_bucket"] = storage_bucket
                _mem_users[user_id]["last_seen"] = now_dt.isoformat()
                return True
            return False

    def create_job(self, job_id: str, total_images: int = 0, user_id: str = "anonymous", folder: str = "default", tenant_id: str = "default") -> None:
        _run_sync(db_create_job(user_id=user_id, folder=folder, total_files=total_images, job_id=job_id, tenant_id=tenant_id))

    def update_job(self, job_id: str, processed_images: int, status: str = "completed", error: Optional[str] = None, tenant_id: Optional[str] = None) -> None:
        _run_sync(db_update_job(job_id, {"processed_files": processed_images, "status": status, "error": error}, tenant_id=tenant_id))

    def get_job_by_id(self, job_id: str, tenant_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        job = _run_sync(db_get_job(job_id, tenant_id=tenant_id))
        if not job:
            return None
        logs = job.get("logs", [])
        if isinstance(logs, str):
            try:
                logs = json.loads(logs)
            except Exception:
                logs = []
        return {
            "job_id": job["job_id"],
            "status": job["status"],
            "total_images": job.get("total_files", 0),
            "processed_images": job.get("processed_files", 0),
            "total_files": job.get("total_files", 0),
            "processed_files": job.get("processed_files", 0),
            "current_stage": job.get("status"),
            "logs": logs,
            "error_message": job.get("error"),
            "created_at": str(job.get("created_at")),
            "updated_at": str(job.get("updated_at")),
        }

    def append_job_log(self, job_id: str, message: str, tenant_id: Optional[str] = None) -> None:
        _run_sync(db_append_job_log(job_id, message, tenant_id=tenant_id))

    def save_face_cluster(
        self,
        cluster_id: str,
        person_name: str,
        face_count: int,
        sample_crop_urls: List[str],
        user_id: str = "system",
        folder: Optional[str] = None,
        tenant_id: Optional[str] = None,
    ) -> None:
        rep_url = sample_crop_urls[0] if sample_crop_urls else ""
        _run_sync(db_upsert_cluster(
            cluster_id=cluster_id,
            person_name=person_name,
            face_count=face_count,
            representative_face_url=rep_url,
            user_id=user_id,
            folder=folder,
            tenant_id=tenant_id,
        ))

    def get_all_face_clusters(
        self,
        folder: Optional[str] = None,
        user_id: Optional[str] = None,
        tenant_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        tid = (tenant_id or get_current_tenant_id()).strip()
        pool = _run_sync(get_postgres_pool()) if is_postgres_configured() else None

        if pool:
            async def _get():
                async with get_tenant_connection(tid) as conn:
                    query = "SELECT * FROM face_clusters WHERE 1=1"
                    params = []
                    idx = 1
                    if folder:
                        query += f" AND folder = ${idx}"
                        params.append(folder)
                        idx += 1
                    if user_id and user_id != "system":
                        query += f" AND (user_id = ${idx} OR user_id = 'system')"
                        params.append(user_id)
                        idx += 1
                    query += " ORDER BY face_count DESC"
                    rows = await conn.fetch(query, *params)
                    return [
                        {
                            "cluster_id": r["cluster_id"],
                            "person_name": r["person_name"] or "Unnamed Person",
                            "face_count": r["face_count"],
                            "folder": r["folder"],
                            "sample_crop_urls": [r["representative_face_url"]] if r["representative_face_url"] else [],
                            "created_at": str(r["updated_at"]),
                        }
                        for r in rows
                    ]
            return _run_sync(_get())

        with _mem_lock:
            results = []
            for c in _mem_clusters.values():
                if c.get("tenant_id") == tid:
                    if folder and c.get("folder") != folder:
                        continue
                    if user_id and user_id != "system" and c.get("user_id") not in (user_id, "system"):
                        continue
                    results.append({
                        "cluster_id": c["cluster_id"],
                        "person_name": c["person_name"],
                        "face_count": c["face_count"],
                        "folder": c.get("folder"),
                        "sample_crop_urls": [c["representative_face_url"]] if c.get("representative_face_url") else [],
                        "created_at": c.get("updated_at"),
                    })
            results.sort(key=lambda x: x["face_count"], reverse=True)
            return results

    def update_cluster_name(self, cluster_id: str, new_name: str, tenant_id: Optional[str] = None) -> bool:
        return _run_sync(db_rename_cluster(cluster_id, new_name, user_id="", tenant_id=tenant_id))

    def find_duplicate_by_hash(
        self,
        sha256: str,
        phash: Optional[str] = None,
        tenant_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Searches for duplicate vector record by exact SHA256 or perceptual hash."""
        tid = (tenant_id or get_current_tenant_id()).strip()
        pool = _run_sync(get_postgres_pool()) if is_postgres_configured() else None

        if pool:
            async def _find():
                async with get_tenant_connection(tid) as conn:
                    row = await conn.fetchrow(
                        """
                        SELECT int_id, tenant_id, index_name, vector_id, url, folder, metadata_json
                        FROM vector_metadata
                        WHERE tenant_id = $1
                          AND (
                            metadata_json->>'sha256' = $2
                            OR ($3::text IS NOT NULL AND metadata_json->>'phash' = $3::text)
                          )
                        LIMIT 1
                        """,
                        tid, sha256, phash
                    )
                    if row:
                        meta = json.loads(row["metadata_json"]) if isinstance(row["metadata_json"], str) else row["metadata_json"]
                        return {
                            "int_id": row["int_id"],
                            "vector_id": row["vector_id"],
                            "url": row["url"],
                            "folder": row["folder"],
                            "metadata": meta,
                        }
                    return None
            return _run_sync(_find())

        with _mem_lock:
            for item in _mem_vector_metadata.values():
                if item.get("tenant_id") == tid:
                    meta = item.get("metadata", {})
                    item_sha = meta.get("sha256")
                    item_phash = meta.get("phash")
                    if item_sha and item_sha == sha256:
                        return dict(item)
                    if phash and item_phash and item_phash == phash:
                        return dict(item)
            return None

    # ===============================================================
    # Enterprise Multi-Tenant, RBAC & Folder ACL Operations
    # ===============================================================

    def create_tenant(self, tenant_id: str, name: str, storage_bucket: str = "visual-search-media") -> bool:
        """Create or update a tenant organization record."""
        pool = _run_sync(get_postgres_pool()) if is_postgres_configured() else None
        now_dt = datetime.now(timezone.utc)
        if pool:
            async def _create():
                async with get_bypass_rls_connection() as conn:
                    await conn.execute(
                        """
                        INSERT INTO tenants (tenant_id, name, storage_bucket, is_active, created_at, updated_at)
                        VALUES ($1, $2, $3, TRUE, $4, $4)
                        ON CONFLICT (tenant_id) DO UPDATE
                        SET name = EXCLUDED.name, storage_bucket = EXCLUDED.storage_bucket, updated_at = EXCLUDED.updated_at
                        """,
                        tenant_id, name, storage_bucket, now_dt
                    )
                    return True
            return _run_sync(_create())

        with _mem_lock:
            _mem_tenants[tenant_id] = {
                "tenant_id": tenant_id,
                "name": name,
                "storage_bucket": storage_bucket,
                "is_active": True,
                "created_at": now_dt.isoformat(),
                "updated_at": now_dt.isoformat(),
            }
            return True

    def get_tenant_by_id(self, tenant_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve tenant details by ID."""
        pool = _run_sync(get_postgres_pool()) if is_postgres_configured() else None
        if pool:
            async def _get():
                async with get_bypass_rls_connection() as conn:
                    row = await conn.fetchrow("SELECT * FROM tenants WHERE tenant_id = $1", tenant_id)
                    return dict(row) if row else None
            return _run_sync(_get())

        with _mem_lock:
            return dict(_mem_tenants[tenant_id]) if tenant_id in _mem_tenants else None

    def get_user_preauth(self, username_or_email: str) -> Optional[Dict[str, Any]]:
        """
        Bypasses RLS to fetch a user by email or username prior to authentication.
        Solves Trap 1 (Chicken-and-Egg RLS Deadlock on login).
        """
        clean_key = username_or_email.strip().lower()
        pool = _run_sync(get_postgres_pool()) if is_postgres_configured() else None
        if pool:
            async def _get():
                async with get_bypass_rls_connection() as conn:
                    row = await conn.fetchrow(
                        "SELECT * FROM users WHERE LOWER(email) = $1 OR username = $2 LIMIT 1",
                        clean_key, username_or_email.strip()
                    )
                    return dict(row) if row else None
            return _run_sync(_get())

        with _mem_lock:
            for u in _mem_users.values():
                if u.get("email", "").lower() == clean_key or u.get("username") == username_or_email.strip():
                    return dict(u)
            return None

    def create_tenant_invite(
        self,
        invite_id: str,
        tenant_id: str,
        email: str,
        role: str,
        initial_folder_ids: List[str],
        initial_access_level: str,
        invited_by: str,
        invite_token: str,
        expires_at: datetime,
    ) -> bool:
        """Create a tenant invitation record with pre-assigned folder IDs."""
        tid = tenant_id.strip()
        clean_email = email.strip().lower()
        now_dt = datetime.now(timezone.utc)
        pool = _run_sync(get_postgres_pool()) if is_postgres_configured() else None

        if pool:
            async def _create():
                async with get_tenant_connection(tid) as conn:
                    await conn.execute(
                        """
                        INSERT INTO tenant_invites (
                            invite_id, tenant_id, email, role, initial_folder_ids,
                            initial_access_level, invited_by, invite_token, expires_at, created_at
                        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                        """,
                        invite_id, tid, clean_email, role, initial_folder_ids,
                        initial_access_level, invited_by, invite_token, expires_at, now_dt
                    )
                    return True
            return _run_sync(_create())

        with _mem_lock:
            _mem_invites[invite_token] = {
                "invite_id": invite_id,
                "tenant_id": tid,
                "email": clean_email,
                "role": role,
                "initial_folder_ids": list(initial_folder_ids),
                "initial_access_level": initial_access_level,
                "invited_by": invited_by,
                "invite_token": invite_token,
                "expires_at": expires_at.isoformat(),
                "accepted_at": None,
                "created_at": now_dt.isoformat(),
            }
            return True

    def get_invite_by_token(self, invite_token: str) -> Optional[Dict[str, Any]]:
        """
        Bypasses RLS to fetch a valid, unaccepted, non-expired invite record by token,
        joined with tenants to provide organization_name and storage_bucket.
        """
        token = invite_token.strip()
        pool = _run_sync(get_postgres_pool()) if is_postgres_configured() else None

        if pool:
            async def _get():
                async with get_bypass_rls_connection() as conn:
                    row = await conn.fetchrow(
                        """
                        SELECT 
                            ti.invite_id,
                            ti.tenant_id,
                            t.name AS organization_name,
                            t.storage_bucket,
                            ti.email,
                            ti.role,
                            ti.initial_folder_ids,
                            ti.initial_access_level,
                            ti.invited_by,
                            ti.expires_at,
                            ti.accepted_at
                        FROM tenant_invites ti
                        JOIN tenants t ON ti.tenant_id = t.tenant_id
                        WHERE ti.invite_token = $1 AND ti.accepted_at IS NULL AND ti.expires_at > NOW()
                        LIMIT 1
                        """,
                        token
                    )
                    return dict(row) if row else None
            return _run_sync(_get())

        with _mem_lock:
            inv = _mem_invites.get(token)
            if not inv or inv.get("accepted_at"):
                return None
            exp = datetime.fromisoformat(inv["expires_at"]) if isinstance(inv["expires_at"], str) else inv["expires_at"]
            if exp < datetime.now(timezone.utc):
                return None
            res = dict(inv)
            t = _mem_tenants.get(inv["tenant_id"], {})
            res["organization_name"] = t.get("name", "Organization")
            res["storage_bucket"] = t.get("storage_bucket", "visual-search-media")
            return res

    def get_active_invite_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        """
        Checks if an email has an active pending unaccepted invite elsewhere to prevent orphan tenant creation.
        """
        clean_email = email.strip().lower()
        pool = _run_sync(get_postgres_pool()) if is_postgres_configured() else None

        if pool:
            async def _get():
                async with get_bypass_rls_connection() as conn:
                    row = await conn.fetchrow(
                        """
                        SELECT 
                            ti.invite_id,
                            ti.tenant_id,
                            t.name AS organization_name,
                            ti.role,
                            ti.expires_at
                        FROM tenant_invites ti
                        JOIN tenants t ON ti.tenant_id = t.tenant_id
                        WHERE LOWER(ti.email) = LOWER($1)
                          AND ti.accepted_at IS NULL
                          AND ti.expires_at > NOW()
                        ORDER BY ti.created_at DESC
                        LIMIT 1
                        """,
                        clean_email
                    )
                    return dict(row) if row else None
            return _run_sync(_get())

        with _mem_lock:
            now_dt = datetime.now(timezone.utc)
            for inv in _mem_invites.values():
                if inv.get("email", "").lower() == clean_email and not inv.get("accepted_at"):
                    exp = datetime.fromisoformat(inv["expires_at"]) if isinstance(inv["expires_at"], str) else inv["expires_at"]
                    if exp > now_dt:
                        res = dict(inv)
                        t = _mem_tenants.get(inv["tenant_id"], {})
                        res["organization_name"] = t.get("name", "Organization")
                        return res
            return None

    def get_users_by_email_preauth(self, email: str) -> List[Dict[str, Any]]:
        """
        Pre-auth lookup returning all active accounts matching an email across tenants.
        Enables multi-tenant login disambiguation.
        """
        clean_email = email.strip().lower()
        pool = _run_sync(get_postgres_pool()) if is_postgres_configured() else None

        if pool:
            async def _get():
                async with get_bypass_rls_connection() as conn:
                    rows = await conn.fetch(
                        """
                        SELECT 
                            u.user_id,
                            u.tenant_id,
                            u.username,
                            u.email,
                            u.hashed_password,
                            u.role,
                            u.is_active,
                            u.storage_bucket,
                            u.created_at,
                            u.last_seen,
                            t.name AS organization_name
                        FROM users u
                        JOIN tenants t ON u.tenant_id = t.tenant_id
                        WHERE LOWER(u.email) = LOWER($1) AND u.is_active = TRUE
                        """,
                        clean_email
                    )
                    return [dict(r) for r in rows]
            return _run_sync(_get())

        with _mem_lock:
            results = []
            for u in _mem_users.values():
                if u.get("email", "").lower() == clean_email and u.get("is_active", True):
                    rec = dict(u)
                    t = _mem_tenants.get(u.get("tenant_id", ""), {})
                    rec["organization_name"] = t.get("name", "Organization")
                    results.append(rec)
            return results

    def get_user_by_tenant_and_email(self, tenant_id: str, email: str) -> Optional[Dict[str, Any]]:
        """Fetch user scoped to specific tenant by email."""
        tid = tenant_id.strip()
        clean_email = email.strip().lower()
        pool = _run_sync(get_postgres_pool()) if is_postgres_configured() else None

        if pool:
            async def _get():
                async with get_tenant_connection(tid) as conn:
                    row = await conn.fetchrow(
                        """
                        SELECT u.*, t.name as organization_name 
                        FROM users u
                        JOIN tenants t ON u.tenant_id = t.tenant_id
                        WHERE u.tenant_id = $1 AND LOWER(u.email) = LOWER($2) LIMIT 1
                        """,
                        tid, clean_email
                    )
                    return dict(row) if row else None
            return _run_sync(_get())

        with _mem_lock:
            for u in _mem_users.values():
                if u.get("tenant_id") == tid and u.get("email", "").lower() == clean_email:
                    rec = dict(u)
                    t = _mem_tenants.get(tid, {})
                    rec["organization_name"] = t.get("name", "Organization")
                    return rec
            return None

    def get_user_by_tenant_and_username(self, tenant_id: str, username: str) -> Optional[Dict[str, Any]]:
        """Fetch user scoped to specific tenant by username."""
        tid = tenant_id.strip()
        clean_username = username.strip()
        pool = _run_sync(get_postgres_pool()) if is_postgres_configured() else None

        if pool:
            async def _get():
                async with get_tenant_connection(tid) as conn:
                    row = await conn.fetchrow(
                        "SELECT * FROM users WHERE tenant_id = $1 AND username = $2 LIMIT 1",
                        tid, clean_username
                    )
                    return dict(row) if row else None
            return _run_sync(_get())

        with _mem_lock:
            for u in _mem_users.values():
                if u.get("tenant_id") == tid and u.get("username") == clean_username:
                    return dict(u)
            return None

    def mark_invite_accepted(self, invite_token: str) -> bool:
        """Mark an invite token as consumed."""
        token = invite_token.strip()
        now_dt = datetime.now(timezone.utc)
        pool = _run_sync(get_postgres_pool()) if is_postgres_configured() else None

        if pool:
            async def _accept():
                async with get_bypass_rls_connection() as conn:
                    await conn.execute(
                        "UPDATE tenant_invites SET accepted_at = $1 WHERE invite_token = $2",
                        now_dt, token
                    )
                    return True
            return _run_sync(_accept())

        with _mem_lock:
            if token in _mem_invites:
                _mem_invites[token]["accepted_at"] = now_dt.isoformat()
                return True
            return False

    def list_tenant_members(self, tenant_id: str, limit: int = 50, offset: int = 0) -> List[Dict[str, Any]]:
        """List registered members in a tenant with pagination."""
        tid = tenant_id.strip()
        lim = max(1, min(limit, 200))
        off = max(0, offset)
        pool = _run_sync(get_postgres_pool()) if is_postgres_configured() else None

        if pool:
            async def _list():
                async with get_tenant_connection(tid) as conn:
                    rows = await conn.fetch(
                        """
                        SELECT user_id, username, email, role, is_active, created_at, last_seen
                        FROM users WHERE tenant_id = $1 ORDER BY created_at ASC
                        LIMIT $2 OFFSET $3
                        """,
                        tid, lim, off
                    )
                    return [dict(r) for r in rows]
            return _run_sync(_list())

        with _mem_lock:
            results = []
            for u in _mem_users.values():
                if u.get("tenant_id") == tid:
                    results.append({
                        "user_id": u["user_id"],
                        "username": u.get("username", ""),
                        "email": u.get("email", ""),
                        "role": u.get("role", "viewer"),
                        "is_active": u.get("is_active", True),
                        "created_at": str(u.get("created_at", "")),
                        "last_seen": str(u.get("last_seen", "")),
                    })
            results.sort(key=lambda x: x["created_at"])
            return results[off:off + lim]

    def update_tenant_member_role(self, tenant_id: str, user_id: str, role: str) -> bool:
        """Update a member's Tier 1 tenant-wide role."""
        tid = tenant_id.strip()
        uid = user_id.strip()
        now_dt = datetime.now(timezone.utc)
        pool = _run_sync(get_postgres_pool()) if is_postgres_configured() else None

        if pool:
            async def _update():
                async with get_tenant_connection(tid) as conn:
                    res = await conn.execute(
                        "UPDATE users SET role = $1, last_seen = $2 WHERE tenant_id = $3 AND user_id = $4",
                        role, now_dt, tid, uid
                    )
                    return "UPDATE 1" in res
            return _run_sync(_update())

        with _mem_lock:
            if uid in _mem_users and _mem_users[uid].get("tenant_id") == tid:
                _mem_users[uid]["role"] = role
                _mem_users[uid]["last_seen"] = now_dt.isoformat()
                return True
            return False

    def remove_tenant_member(self, tenant_id: str, user_id: str) -> bool:
        """Remove a member from a tenant."""
        tid = tenant_id.strip()
        uid = user_id.strip()
        pool = _run_sync(get_postgres_pool()) if is_postgres_configured() else None

        if pool:
            async def _del():
                async with get_tenant_connection(tid) as conn:
                    res = await conn.execute(
                        "DELETE FROM users WHERE tenant_id = $1 AND user_id = $2",
                        tid, uid
                    )
                    return "DELETE 1" in res
            return _run_sync(_del())

        with _mem_lock:
            if uid in _mem_users and _mem_users[uid].get("tenant_id") == tid:
                del _mem_users[uid]
                return True
            return False

    def create_folder(
        self,
        folder_id: Optional[str] = None,
        tenant_id: str = "",
        folder_name: str = "",
        description: Optional[str] = None,
        visibility: str = "restricted",
        created_by: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Creates a new folder and atomically grants the creator 'manager' access level.
        Prevents the Orphaned Folder Creator Bug.
        """
        fid = (folder_id or f"fld_{uuid.uuid4().hex[:12]}").strip()
        tid = tenant_id.strip()
        now_dt = datetime.now(timezone.utc)
        clean_name = folder_name.strip()
        pool = _run_sync(get_postgres_pool()) if is_postgres_configured() else None

        if pool:
            async def _create():
                async with get_tenant_connection(tid) as conn:
                    # Insert folder
                    await conn.execute(
                        """
                        INSERT INTO folders (folder_id, tenant_id, folder_name, description, visibility, photo_count, created_by, created_at, updated_at)
                        VALUES ($1, $2, $3, $4, $5, 0, $6, $7, $7)
                        """,
                        fid, tid, clean_name, description, visibility, created_by, now_dt
                    )
                    # Atomically grant creator 'manager' access
                    if created_by:
                        await conn.execute(
                            """
                            INSERT INTO folder_user_access (folder_id, user_id, tenant_id, access_level, granted_by, created_at)
                            VALUES ($1, $2, $3, 'manager', $2, $4)
                            ON CONFLICT (folder_id, user_id) DO UPDATE SET access_level = 'manager'
                            """,
                            fid, created_by, tid, now_dt
                        )
                    return True
            _run_sync(_create())
        else:
            with _mem_lock:
                # Check unique folder name in tenant
                for f in _mem_folders.values():
                    if f.get("tenant_id") == tid and f.get("folder_name") == clean_name:
                        raise ValueError(f"Folder '{clean_name}' already exists in tenant")
                _mem_folders[fid] = {
                    "folder_id": fid,
                    "tenant_id": tid,
                    "folder_name": clean_name,
                    "description": description,
                    "visibility": visibility,
                    "photo_count": 0,
                    "created_by": created_by,
                    "created_at": now_dt.isoformat(),
                    "updated_at": now_dt.isoformat(),
                }
                if created_by:
                    _mem_folder_access[(fid, created_by)] = {
                        "folder_id": fid,
                        "user_id": created_by,
                        "tenant_id": tid,
                        "access_level": "manager",
                        "granted_by": created_by,
                        "created_at": now_dt.isoformat(),
                    }

        return {
            "folder_id": fid,
            "tenant_id": tid,
            "folder_name": clean_name,
            "description": description,
            "visibility": visibility,
            "photo_count": 0,
            "created_by": created_by,
            "created_at": now_dt.isoformat(),
        }

    def get_folder_by_id(self, folder_id: str, tenant_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve folder by ID scoped to tenant."""
        tid = tenant_id.strip()
        fid = folder_id.strip()
        pool = _run_sync(get_postgres_pool()) if is_postgres_configured() else None

        if pool:
            async def _get():
                async with get_tenant_connection(tid) as conn:
                    row = await conn.fetchrow(
                        "SELECT * FROM folders WHERE tenant_id = $1 AND folder_id = $2",
                        tid, fid
                    )
                    return dict(row) if row else None
            return _run_sync(_get())

        with _mem_lock:
            f = _mem_folders.get(fid)
            if f and f.get("tenant_id") == tid:
                return dict(f)
            return None

    def get_folder_by_name(self, folder_name: str, tenant_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve folder by name scoped to tenant."""
        tid = tenant_id.strip()
        fname = folder_name.strip()
        pool = _run_sync(get_postgres_pool()) if is_postgres_configured() else None

        if pool:
            async def _get():
                async with get_tenant_connection(tid) as conn:
                    row = await conn.fetchrow(
                        "SELECT * FROM folders WHERE tenant_id = $1 AND folder_name = $2",
                        tid, fname
                    )
                    return dict(row) if row else None
            return _run_sync(_get())

        with _mem_lock:
            for f in _mem_folders.values():
                if f.get("tenant_id") == tid and f.get("folder_name") == fname:
                    return dict(f)
            return None

    def update_folder(
        self,
        folder_id: str,
        tenant_id: str,
        folder_name: Optional[str] = None,
        description: Optional[str] = None,
        visibility: Optional[str] = None,
    ) -> bool:
        """Update folder attributes."""
        tid = tenant_id.strip()
        fid = folder_id.strip()
        now_dt = datetime.now(timezone.utc)
        pool = _run_sync(get_postgres_pool()) if is_postgres_configured() else None

        if pool:
            async def _update():
                async with get_tenant_connection(tid) as conn:
                    current = await conn.fetchrow("SELECT * FROM folders WHERE tenant_id = $1 AND folder_id = $2", tid, fid)
                    if not current:
                        return False
                    new_name = folder_name.strip() if folder_name else current["folder_name"]
                    new_desc = description if description is not None else current["description"]
                    new_vis = visibility if visibility else current["visibility"]
                    res = await conn.execute(
                        """
                        UPDATE folders SET folder_name = $1, description = $2, visibility = $3, updated_at = $4
                        WHERE tenant_id = $5 AND folder_id = $6
                        """,
                        new_name, new_desc, new_vis, now_dt, tid, fid
                    )
                    return "UPDATE 1" in res
            return _run_sync(_update())

        with _mem_lock:
            f = _mem_folders.get(fid)
            if not f or f.get("tenant_id") != tid:
                return False
            if folder_name:
                f["folder_name"] = folder_name.strip()
            if description is not None:
                f["description"] = description
            if visibility:
                f["visibility"] = visibility
            f["updated_at"] = now_dt.isoformat()
            return True

    def delete_folder(self, folder_id: str, tenant_id: str) -> bool:
        """Delete folder and its member mappings."""
        tid = tenant_id.strip()
        fid = folder_id.strip()
        pool = _run_sync(get_postgres_pool()) if is_postgres_configured() else None

        if pool:
            async def _del():
                async with get_tenant_connection(tid) as conn:
                    res = await conn.execute("DELETE FROM folders WHERE tenant_id = $1 AND folder_id = $2", tid, fid)
                    return "DELETE 1" in res
            return _run_sync(_del())

        with _mem_lock:
            if fid in _mem_folders and _mem_folders[fid].get("tenant_id") == tid:
                del _mem_folders[fid]
                keys_to_del = [k for k in _mem_folder_access if k[0] == fid]
                for k in keys_to_del:
                    del _mem_folder_access[k]
                return True
            return False

    def set_folder_access(
        self,
        folder_id: str,
        user_id: str,
        tenant_id: str,
        access_level: str,
        granted_by: Optional[str] = None,
    ) -> bool:
        """Set or update a user's access level for a specific folder."""
        tid = tenant_id.strip()
        fid = folder_id.strip()
        uid = user_id.strip()
        now_dt = datetime.now(timezone.utc)
        pool = _run_sync(get_postgres_pool()) if is_postgres_configured() else None

        if pool:
            async def _set():
                async with get_tenant_connection(tid) as conn:
                    await conn.execute(
                        """
                        INSERT INTO folder_user_access (folder_id, user_id, tenant_id, access_level, granted_by, created_at)
                        VALUES ($1, $2, $3, $4, $5, $6)
                        ON CONFLICT (folder_id, user_id) DO UPDATE
                        SET access_level = EXCLUDED.access_level, granted_by = EXCLUDED.granted_by
                        """,
                        fid, uid, tid, access_level, granted_by, now_dt
                    )
                    return True
            return _run_sync(_set())

        with _mem_lock:
            _mem_folder_access[(fid, uid)] = {
                "folder_id": fid,
                "user_id": uid,
                "tenant_id": tid,
                "access_level": access_level,
                "granted_by": granted_by,
                "created_at": now_dt.isoformat(),
            }
            return True

    def bulk_set_folder_access(
        self,
        tenant_id: str,
        folder_ids: List[str],
        user_ids: List[str],
        access_level: str,
        granted_by: Optional[str] = None,
    ) -> int:
        """Bulk assign multiple users to multiple folders in one high-efficiency operation."""
        count = 0
        for fid in folder_ids:
            for uid in user_ids:
                if self.set_folder_access(fid, uid, tenant_id, access_level, granted_by):
                    count += 1
        return count

    def remove_folder_access(self, folder_id: str, user_id: str, tenant_id: str) -> bool:
        """Revoke a user's explicit folder access record."""
        tid = tenant_id.strip()
        fid = folder_id.strip()
        uid = user_id.strip()
        pool = _run_sync(get_postgres_pool()) if is_postgres_configured() else None

        if pool:
            async def _del():
                async with get_tenant_connection(tid) as conn:
                    res = await conn.execute(
                        "DELETE FROM folder_user_access WHERE tenant_id = $1 AND folder_id = $2 AND user_id = $3",
                        tid, fid, uid
                    )
                    return "DELETE 1" in res
            return _run_sync(_del())

        with _mem_lock:
            key = (fid, uid)
            if key in _mem_folder_access:
                del _mem_folder_access[key]
                return True
            return False

    def get_folder_members(self, folder_id: str, tenant_id: str) -> List[Dict[str, Any]]:
        """List all users who have explicit access records for this folder."""
        tid = tenant_id.strip()
        fid = folder_id.strip()
        pool = _run_sync(get_postgres_pool()) if is_postgres_configured() else None

        if pool:
            async def _members():
                async with get_tenant_connection(tid) as conn:
                    rows = await conn.fetch(
                        """
                        SELECT u.user_id, u.username, u.email, u.role as tenant_role,
                               fua.access_level, fua.granted_by, fua.created_at
                        FROM folder_user_access fua
                        JOIN users u ON fua.user_id = u.user_id
                        WHERE fua.tenant_id = $1 AND fua.folder_id = $2
                        ORDER BY fua.created_at ASC
                        """,
                        tid, fid
                    )
                    return [dict(r) for r in rows]
            return _run_sync(_members())

        with _mem_lock:
            results = []
            for (f_id, u_id), a in _mem_folder_access.items():
                if f_id == fid and a.get("tenant_id") == tid:
                    u = _mem_users.get(u_id, {})
                    results.append({
                        "user_id": u_id,
                        "username": u.get("username", "Unknown"),
                        "email": u.get("email", ""),
                        "tenant_role": u.get("role", "viewer"),
                        "access_level": a.get("access_level", "inherit"),
                        "granted_by": a.get("granted_by"),
                        "created_at": a.get("created_at", ""),
                    })
            return results

    def resolve_user_accessible_folders(
        self,
        user_id: str,
        tenant_id: str,
        role: str,
    ) -> List[Dict[str, Any]]:
        """
        Executes the Single-Query Permission & Accessible Folders Resolver.
        Evaluates tenant_wide visibility, explicit folder_user_access overrides,
        and strictly excludes folders where access_level == 'revoked'.
        """
        tid = tenant_id.strip()
        uid = user_id.strip()
        urole = (role or "viewer").strip().lower()
        pool = _run_sync(get_postgres_pool()) if is_postgres_configured() else None

        if pool:
            async def _resolve():
                async with get_tenant_connection(tid) as conn:
                    rows = await conn.fetch(
                        """
                        SELECT 
                            f.folder_id,
                            f.folder_name,
                            f.description,
                            f.visibility,
                            f.photo_count,
                            f.created_by,
                            f.created_at,
                            CASE
                                WHEN $3 IN ('owner', 'admin') THEN 'manager'
                                WHEN fua.access_level IS NOT NULL AND fua.access_level != 'inherit' THEN fua.access_level
                                WHEN $3 = 'editor' THEN 'editor'
                                WHEN $3 = 'contributor' THEN 'uploader'
                                ELSE 'viewer'
                            END AS effective_access
                        FROM folders f
                        LEFT JOIN folder_user_access fua 
                               ON f.folder_id = fua.folder_id AND fua.user_id = $1
                        WHERE f.tenant_id = $2
                          AND (
                              $3 IN ('owner', 'admin')
                              OR (
                                  COALESCE(fua.access_level, 'inherit') != 'revoked'
                                  AND (f.visibility = 'tenant_wide' OR fua.user_id IS NOT NULL)
                              )
                          )
                        ORDER BY f.folder_name ASC
                        """,
                        uid, tid, urole
                    )
                    res = []
                    for r in rows:
                        item = dict(r)
                        eff = item["effective_access"]
                        item["can_upload"] = eff in ("uploader", "editor", "manager")
                        item["can_delete"] = eff in ("editor", "manager")
                        item["can_manage"] = eff == "manager"
                        item["created_at"] = str(item["created_at"])
                        res.append(item)
                    return res
            return _run_sync(_resolve())

        with _mem_lock:
            res = []
            for f in _mem_folders.values():
                if f.get("tenant_id") != tid:
                    continue
                fid = f["folder_id"]
                vis = f.get("visibility", "restricted")
                acl = _mem_folder_access.get((fid, uid))

                if urole in ("owner", "admin"):
                    effective = "manager"
                elif acl and acl.get("access_level") == "revoked":
                    continue  # Trap 2: Explicitly revoked from tenant_wide or restricted
                elif acl and acl.get("access_level") not in (None, "inherit"):
                    effective = acl["access_level"]
                elif vis == "tenant_wide":
                    if urole == "editor":
                        effective = "editor"
                    elif urole == "contributor":
                        effective = "uploader"
                    else:
                        effective = "viewer"
                elif acl and acl.get("access_level") == "inherit":
                    if urole == "editor":
                        effective = "editor"
                    elif urole == "contributor":
                        effective = "uploader"
                    else:
                        effective = "viewer"
                else:
                    continue  # Restricted folder with no access record

                res.append({
                    "folder_id": fid,
                    "folder_name": f.get("folder_name", ""),
                    "description": f.get("description"),
                    "visibility": vis,
                    "photo_count": f.get("photo_count", 0),
                    "created_by": f.get("created_by"),
                    "created_at": str(f.get("created_at", "")),
                    "effective_access": effective,
                    "can_upload": effective in ("uploader", "editor", "manager"),
                    "can_delete": effective in ("editor", "manager"),
                    "can_manage": effective == "manager",
                })
            res.sort(key=lambda x: x["folder_name"])
            return res


_repo_instance: Optional[PostgresRepository] = None


def get_repository() -> PostgresRepository:
    """Retrieve singleton instance of PostgresRepository."""
    global _repo_instance
    if _repo_instance is None:
        _repo_instance = PostgresRepository()
    return _repo_instance


get_postgres_repo = get_repository

