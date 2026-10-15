"""
src/modules/infra/postgres_repository.py — Production PostgreSQL Repository with Row-Level Security (RLS).
Replaces legacy SQLite with PostgreSQL async connection pooling (asyncpg) and kernel-level tenant isolation.
Provides zero-dependency in-memory fallback for local offline unit testing when PostgreSQL is not running.
"""
import asyncio
import concurrent.futures
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


async def init_postgres_tables() -> None:
    """Initialize PostgreSQL tables, composite indexes, and RLS policies."""
    pool = await get_postgres_pool()
    if not pool:
        return

    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS tenants (
                    tenant_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );

                CREATE TABLE IF NOT EXISTS users (
                    user_id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL DEFAULT 'default',
                    username TEXT,
                    email TEXT,
                    hashed_password TEXT,
                    role TEXT DEFAULT 'user',
                    cloudinary_url TEXT,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    last_seen TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
                CREATE INDEX IF NOT EXISTS idx_pg_users_tenant ON users(tenant_id);
                CREATE INDEX IF NOT EXISTS idx_pg_users_email ON users(tenant_id, email);

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

                CREATE TABLE IF NOT EXISTS face_vector_clusters (
                    vector_id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL DEFAULT 'default',
                    user_id TEXT NOT NULL,
                    cluster_id TEXT NOT NULL,
                    image_url TEXT,
                    folder TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_pg_fvc_tenant ON face_vector_clusters(tenant_id, cluster_id);

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

            # Apply Row-Level Security (RLS) Policies
            for table in ["vector_metadata", "face_clusters", "face_vector_clusters", "upload_jobs"]:
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

            logger.info("PostgreSQL tables and Row-Level Security policies active")


def _run_sync(coro):
    """Safely execute an asynchronous coroutine from synchronous contexts."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        return executor.submit(asyncio.run, coro).result()


# ===============================================================
# In-Memory Fallback State (Zero-dependency for unit testing)
# ===============================================================
_mem_lock = threading.RLock()
_mem_users: Dict[str, dict] = {}           # user_id -> dict
_mem_jobs: Dict[str, dict] = {}            # job_id -> dict
_mem_clusters: Dict[str, dict] = {}        # cluster_id -> dict
_mem_vector_clusters: Dict[str, dict] = {} # vector_id -> dict
_mem_vector_metadata: Dict[int, dict] = {} # int_id -> dict
_mem_int_counter: int = 1


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


async def get_user_by_email(email: str, tenant_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Retrieve user record by email."""
    tid = (tenant_id or get_current_tenant_id()).strip()
    clean_email = email.strip().lower()
    pool = await get_postgres_pool()
    if pool:
        async with get_tenant_connection(tid) as conn:
            row = await conn.fetchrow("SELECT * FROM users WHERE LOWER(email) = $1", clean_email)
            return dict(row) if row else None

    with _mem_lock:
        for u in _mem_users.values():
            if (u.get("email") or "").lower() == clean_email:
                return dict(u)
        return None


async def create_user_record(
    username: str,
    email: str,
    hashed_password: str,
    role: str = "user",
    tenant_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a new registered user in PostgreSQL."""
    user_id = str(uuid.uuid4())
    tid = (tenant_id or get_current_tenant_id()).strip()
    clean_email = email.strip().lower()
    now_dt = datetime.now(timezone.utc)
    now_str = now_dt.isoformat()

    pool = await get_postgres_pool()
    if pool:
        async with get_tenant_connection(tid) as conn:
            await conn.execute(
                """
                INSERT INTO users (user_id, tenant_id, username, email, hashed_password, role, created_at, last_seen)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $7)
                """,
                user_id, tid, username.strip(), clean_email, hashed_password, role, now_dt
            )
        return {
            "user_id": user_id,
            "tenant_id": tid,
            "username": username.strip(),
            "email": clean_email,
            "role": role,
            "created_at": now_str,
        }

    with _mem_lock:
        record = {
            "user_id": user_id,
            "tenant_id": tid,
            "username": username.strip(),
            "email": clean_email,
            "hashed_password": hashed_password,
            "role": role,
            "created_at": now_str,
            "last_seen": now_str,
        }
        _mem_users[user_id] = record
        return record


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


async def db_upsert_vector_clusters(rows: List[dict], tenant_id: Optional[str] = None) -> None:
    """Bulk upsert mapping of vector_ids to cluster_ids."""
    if not rows:
        return
    tid = (tenant_id or get_current_tenant_id()).strip()
    pool = await get_postgres_pool()
    if pool:
        async with get_tenant_connection(tid) as conn:
            for r in rows:
                await conn.execute(
                    """
                    INSERT INTO face_vector_clusters (vector_id, tenant_id, user_id, cluster_id, image_url, folder)
                    VALUES ($1, $2, $3, $4, $5, $6)
                    ON CONFLICT(vector_id) DO UPDATE SET
                        cluster_id = EXCLUDED.cluster_id,
                        image_url = EXCLUDED.image_url,
                        folder = EXCLUDED.folder
                    """,
                    r["vector_id"], tid, r.get("user_id", "system"), r["cluster_id"], r.get("image_url"), r.get("folder")
                )
        return

    with _mem_lock:
        for r in rows:
            _mem_vector_clusters[r["vector_id"]] = dict(r)
            _mem_vector_clusters[r["vector_id"]]["tenant_id"] = tid


async def db_get_clusters_for_user(user_id: str, tenant_id: Optional[str] = None) -> List[dict]:
    """Retrieve all face clusters for a user ordered by face count descending."""
    tid = (tenant_id or get_current_tenant_id()).strip()
    pool = await get_postgres_pool()
    if pool:
        async with get_tenant_connection(tid) as conn:
            rows = await conn.fetch(
                """
                SELECT cluster_id, person_name, representative_face_url, face_count, updated_at
                FROM face_clusters
                WHERE user_id = $1
                ORDER BY face_count DESC
                """,
                user_id
            )
            return [dict(r) for r in rows]

    with _mem_lock:
        results = [
            c for c in _mem_clusters.values()
            if c.get("tenant_id") == tid and (c.get("user_id") == user_id or c.get("user_id") == "system")
        ]
        results.sort(key=lambda x: x.get("face_count", 0), reverse=True)
        return results


async def db_get_cluster_images(cluster_id: str, user_id: str, tenant_id: Optional[str] = None) -> List[dict]:
    """Retrieve all distinct images associated with a specific cluster."""
    tid = (tenant_id or get_current_tenant_id()).strip()
    pool = await get_postgres_pool()
    if pool:
        async with get_tenant_connection(tid) as conn:
            rows = await conn.fetch(
                """
                SELECT DISTINCT image_url, folder
                FROM face_vector_clusters
                WHERE cluster_id = $1 AND user_id = $2 AND image_url IS NOT NULL
                """,
                cluster_id, user_id
            )
            return [dict(r) for r in rows]

    with _mem_lock:
        results = []
        seen = set()
        for v in _mem_vector_clusters.values():
            if v.get("tenant_id") == tid and v.get("cluster_id") == cluster_id and v.get("user_id") == user_id:
                url = v.get("image_url")
                if url and url not in seen:
                    seen.add(url)
                    results.append({"image_url": url, "folder": v.get("folder")})
        return results


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

    def get_user_by_username(self, username: str, tenant_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        tid = (tenant_id or get_current_tenant_id()).strip()
        pool = _run_sync(get_postgres_pool()) if is_postgres_configured() else None
        if pool:
            async def _get():
                async with get_tenant_connection(tid) as conn:
                    row = await conn.fetchrow("SELECT * FROM users WHERE username = $1", username)
                    return dict(row) if row else None
            return _run_sync(_get())

        with _mem_lock:
            for u in _mem_users.values():
                if u.get("tenant_id") == tid and u.get("username") == username:
                    return dict(u)
            return None

    def get_user_by_email(self, email: str, tenant_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        return _run_sync(get_user_by_email(email, tenant_id=tenant_id))

    def get_user_by_id(self, user_id: str, tenant_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        return _run_sync(get_user_by_id(user_id, tenant_id=tenant_id))

    def create_user(
        self,
        user_id: str,
        username: str,
        email: str,
        hashed_password: str,
        role: str = "user",
        cloudinary_url: Optional[str] = None,
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
                            INSERT INTO users (user_id, tenant_id, username, email, hashed_password, role, cloudinary_url, created_at, last_seen)
                            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $8)
                            """,
                            user_id, tid, username.strip(), clean_email, hashed_password, role, cloudinary_url, now_dt
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
                "cloudinary_url": cloudinary_url,
                "created_at": now_dt.isoformat(),
                "last_seen": now_dt.isoformat(),
            }
            return True

    def update_user_cloudinary_url(self, user_id: str, cloudinary_url: str, tenant_id: Optional[str] = None) -> bool:
        tid = (tenant_id or get_current_tenant_id()).strip()
        now_dt = datetime.now(timezone.utc)
        pool = _run_sync(get_postgres_pool()) if is_postgres_configured() else None

        if pool:
            async def _update():
                async with get_tenant_connection(tid) as conn:
                    res = await conn.execute(
                        "UPDATE users SET cloudinary_url = $1, last_seen = $2 WHERE user_id = $3",
                        cloudinary_url, now_dt, user_id
                    )
                    return "UPDATE 1" in res
            return _run_sync(_update())

        with _mem_lock:
            if user_id in _mem_users:
                _mem_users[user_id]["cloudinary_url"] = cloudinary_url
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
                            OR ($3 IS NOT NULL AND metadata_json->>'phash' = $3)
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


_repo_instance: Optional[PostgresRepository] = None


def get_repository() -> PostgresRepository:
    """Retrieve singleton instance of PostgresRepository."""
    global _repo_instance
    if _repo_instance is None:
        _repo_instance = PostgresRepository()
    return _repo_instance


get_postgres_repo = get_repository

