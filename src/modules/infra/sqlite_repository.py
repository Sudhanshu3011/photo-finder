"""
src/modules/infra/sqlite_repository.py — High-performance, zero-dependency local SQLite database.
Stores users & credentials, background upload jobs, face clustering albums, vector metadata, and KV cache.
"""
import asyncio
import json
import os
import sqlite3
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from src.core.logging import log

DB_DIR = os.environ.get("DB_DIR", os.path.join(os.getcwd(), "data"))
DB_PATH = os.environ.get("SQLITE_DB_PATH", os.path.join(DB_DIR, "local_storage.db"))


def get_connection() -> sqlite3.Connection:
    """Create a thread-safe connection to the local SQLite database."""
    os.makedirs(DB_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    return conn


def init_database():
    """Initialize SQLite tables for users, jobs, clusters, metadata, and cache."""
    conn = get_connection()
    try:
        with conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id TEXT PRIMARY KEY,
                    username TEXT,
                    email TEXT UNIQUE,
                    hashed_password TEXT,
                    role TEXT DEFAULT 'user',
                    cloudinary_url TEXT,
                    created_at TEXT NOT NULL,
                    last_seen TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS upload_jobs (
                    job_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    folder TEXT NOT NULL,
                    status TEXT NOT NULL,
                    total_files INTEGER DEFAULT 0,
                    processed_files INTEGER DEFAULT 0,
                    result TEXT,
                    error TEXT,
                    payload TEXT,
                    logs TEXT DEFAULT '[]',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS face_clusters (
                    cluster_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    folder TEXT,
                    person_name TEXT,
                    representative_face_url TEXT,
                    face_count INTEGER DEFAULT 0,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS face_vector_clusters (
                    vector_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    cluster_id TEXT NOT NULL,
                    image_url TEXT,
                    folder TEXT
                );

                CREATE TABLE IF NOT EXISTS kv_cache (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    expires_at REAL
                );

                CREATE TABLE IF NOT EXISTS vector_metadata (
                    int_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    index_name TEXT NOT NULL,
                    vector_id TEXT NOT NULL,
                    url TEXT,
                    folder TEXT,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE UNIQUE INDEX IF NOT EXISTS idx_vm_index_vector ON vector_metadata(index_name, vector_id);
                CREATE INDEX IF NOT EXISTS idx_vm_url ON vector_metadata(url);
                CREATE INDEX IF NOT EXISTS idx_vm_folder ON vector_metadata(folder);
            """)

            # Schema migrations for users table if existing
            cols = [row[1] for row in conn.execute("PRAGMA table_info(users)").fetchall()]
            if "username" not in cols:
                conn.execute("ALTER TABLE users ADD COLUMN username TEXT")
            if "email" not in cols:
                conn.execute("ALTER TABLE users ADD COLUMN email TEXT")
            if "hashed_password" not in cols:
                conn.execute("ALTER TABLE users ADD COLUMN hashed_password TEXT")
            if "role" not in cols:
                conn.execute("ALTER TABLE users ADD COLUMN role TEXT DEFAULT 'user'")
            if "cloudinary_url" not in cols:
                conn.execute("ALTER TABLE users ADD COLUMN cloudinary_url TEXT")

            # Schema migrations for face_clusters
            fc_cols = [row[1] for row in conn.execute("PRAGMA table_info(face_clusters)").fetchall()]
            if "folder" not in fc_cols:
                conn.execute("ALTER TABLE face_clusters ADD COLUMN folder TEXT")

            # Schema migrations for upload_jobs
            job_cols = [row[1] for row in conn.execute("PRAGMA table_info(upload_jobs)").fetchall()]
            if "logs" not in job_cols:
                conn.execute("ALTER TABLE upload_jobs ADD COLUMN logs TEXT DEFAULT '[]'")
    finally:
        conn.close()


# Initialize on import
init_database()


# ===============================================================
# User Operations
# ===============================================================

async def get_or_create_anonymous_user(user_id: Optional[str] = None) -> str:
    """Retrieve existing user or generate a persistent anonymous user UUID."""
    now = datetime.now(timezone.utc).isoformat()
    uid = user_id.strip() if (user_id and user_id.strip()) else str(uuid.uuid4())

    def _sync():
        conn = get_connection()
        try:
            with conn:
                row = conn.execute("SELECT user_id FROM users WHERE user_id = ?", (uid,)).fetchone()
                if row:
                    conn.execute("UPDATE users SET last_seen = ? WHERE user_id = ?", (now, uid))
                    return row["user_id"]
                conn.execute(
                    "INSERT INTO users (user_id, role, created_at, last_seen) VALUES (?, 'guest', ?, ?)",
                    (uid, now, now),
                )
                return uid
        finally:
            conn.close()

    return await asyncio.to_thread(_sync)


async def get_user_by_id(user_id: str) -> Optional[Dict[str, Any]]:
    """Fetch user profile record by user_id."""
    def _sync():
        conn = get_connection()
        try:
            row = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    return await asyncio.to_thread(_sync)


async def get_user_by_email(email: str) -> Optional[Dict[str, Any]]:
    """Fetch user record by email address."""
    clean_email = email.strip().lower()
    def _sync():
        conn = get_connection()
        try:
            row = conn.execute("SELECT * FROM users WHERE email = ?", (clean_email,)).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    return await asyncio.to_thread(_sync)


async def create_user_record(
    user_id: str,
    username: str,
    email: str,
    hashed_password: str,
    role: str = "user",
) -> Dict[str, Any]:
    """Insert a registered user into SQLite."""
    now = datetime.now(timezone.utc).isoformat()
    clean_email = email.strip().lower()

    def _sync():
        conn = get_connection()
        try:
            with conn:
                conn.execute(
                    """
                    INSERT INTO users (user_id, username, email, hashed_password, role, created_at, last_seen)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (user_id, username.strip(), clean_email, hashed_password, role, now, now),
                )
            return {
                "user_id": user_id,
                "username": username.strip(),
                "email": clean_email,
                "role": role,
                "created_at": now,
            }
        finally:
            conn.close()

    return await asyncio.to_thread(_sync)


# ===============================================================
# Upload Job Operations
# ===============================================================

async def db_create_job(
    user_id: str,
    folder: str,
    total_files: int,
    payload: Optional[dict] = None,
    job_id: Optional[str] = None,
) -> str:
    """Create a new tracking record for an upload batch."""
    jid = job_id or str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    p_json = json.dumps(payload or {})

    def _sync():
        conn = get_connection()
        try:
            with conn:
                conn.execute(
                    """
                    INSERT INTO upload_jobs (
                        job_id, user_id, folder, status, total_files,
                        processed_files, payload, logs, created_at, updated_at
                    ) VALUES (?, ?, ?, 'pending', ?, 0, ?, '[]', ?, ?)
                    """,
                    (jid, user_id, folder, total_files, p_json, now, now),
                )
            return jid
        finally:
            conn.close()

    return await asyncio.to_thread(_sync)


async def db_update_job(job_id: str, fields: dict) -> None:
    """Update fields on a job record."""
    serialized_fields = {}
    for k, v in fields.items():
        if isinstance(v, (dict, list)):
            serialized_fields[k] = json.dumps(v)
        else:
            serialized_fields[k] = v
    serialized_fields["updated_at"] = datetime.now(timezone.utc).isoformat()
    set_clauses = [f"{k} = ?" for k in serialized_fields.keys()]
    values = list(serialized_fields.values()) + [job_id]

    def _sync():
        conn = get_connection()
        try:
            with conn:
                conn.execute(
                    f"UPDATE upload_jobs SET {', '.join(set_clauses)} WHERE job_id = ?",
                    values,
                )
        finally:
            conn.close()

    await asyncio.to_thread(_sync)


async def db_get_job(job_id: str) -> Optional[dict]:
    """Retrieve full job dictionary by ID."""
    def _sync():
        conn = get_connection()
        try:
            row = conn.execute("SELECT * FROM upload_jobs WHERE job_id = ?", (job_id,)).fetchone()
            if not row:
                return None
            d = dict(row)
            if d.get("result"):
                try:
                    d["result"] = json.loads(d["result"])
                except Exception:
                    pass
            if d.get("payload"):
                try:
                    d["payload"] = json.loads(d["payload"])
                except Exception:
                    pass
            if d.get("logs"):
                try:
                    d["logs"] = json.loads(d["logs"])
                except Exception:
                    d["logs"] = []
            else:
                d["logs"] = []
            return d
        finally:
            conn.close()

    return await asyncio.to_thread(_sync)


async def db_append_job_log(job_id: str, message: str) -> None:
    """Append a timestamped message to the job's execution log array."""
    ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
    entry = f"[{ts}] {message}"

    def _sync():
        conn = get_connection()
        try:
            with conn:
                row = conn.execute("SELECT logs FROM upload_jobs WHERE job_id = ?", (job_id,)).fetchone()
                if not row:
                    return
                current_logs = json.loads(row["logs"]) if row["logs"] else []
                current_logs.append(entry)
                conn.execute(
                    "UPDATE upload_jobs SET logs = ?, updated_at = ? WHERE job_id = ?",
                    (json.dumps(current_logs), datetime.now(timezone.utc).isoformat(), job_id),
                )
        finally:
            conn.close()

    await asyncio.to_thread(_sync)


# ===============================================================
# Face Clustering Operations
# ===============================================================

async def db_upsert_cluster(
    cluster_id: str,
    user_id: str,
    representative_face_url: Optional[str] = None,
    face_count: int = 0,
    person_name: Optional[str] = None,
) -> None:
    """Insert or update a face cluster record."""
    now = datetime.now(timezone.utc).isoformat()

    def _sync():
        conn = get_connection()
        try:
            with conn:
                existing = conn.execute(
                    "SELECT person_name, representative_face_url FROM face_clusters WHERE cluster_id = ? AND user_id = ?",
                    (cluster_id, user_id),
                ).fetchone()

                final_name = person_name
                final_face = representative_face_url
                if existing:
                    if final_name is None:
                        final_name = existing["person_name"]
                    if not final_face:
                        final_face = existing["representative_face_url"]

                conn.execute(
                    """
                    INSERT INTO face_clusters (cluster_id, user_id, person_name, representative_face_url, face_count, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(cluster_id) DO UPDATE SET
                        person_name = coalesce(excluded.person_name, face_clusters.person_name),
                        representative_face_url = coalesce(excluded.representative_face_url, face_clusters.representative_face_url),
                        face_count = excluded.face_count,
                        updated_at = excluded.updated_at
                    """,
                    (cluster_id, user_id, final_name, final_face, face_count, now),
                )
        finally:
            conn.close()

    await asyncio.to_thread(_sync)


async def db_upsert_vector_clusters(rows: List[dict]) -> None:
    """Bulk upsert mapping of vector_ids to cluster_ids."""
    if not rows:
        return

    def _sync():
        conn = get_connection()
        try:
            with conn:
                conn.executemany(
                    """
                    INSERT OR REPLACE INTO face_vector_clusters (vector_id, user_id, cluster_id, image_url, folder)
                    VALUES (:vector_id, :user_id, :cluster_id, :image_url, :folder)
                    """,
                    rows,
                )
        finally:
            conn.close()

    await asyncio.to_thread(_sync)


async def db_get_clusters_for_user(user_id: str) -> List[dict]:
    """Retrieve all clusters for a user ordered by face count descending."""
    def _sync():
        conn = get_connection()
        try:
            rows = conn.execute(
                """
                SELECT cluster_id, person_name, representative_face_url, face_count, updated_at
                FROM face_clusters
                WHERE user_id = ?
                ORDER BY face_count DESC
                """,
                (user_id,),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    return await asyncio.to_thread(_sync)


async def db_get_cluster_images(cluster_id: str, user_id: str) -> List[dict]:
    """Retrieve all images associated with a specific cluster."""
    def _sync():
        conn = get_connection()
        try:
            rows = conn.execute(
                """
                SELECT DISTINCT image_url, folder
                FROM face_vector_clusters
                WHERE cluster_id = ? AND user_id = ? AND image_url IS NOT NULL
                """,
                (cluster_id, user_id),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    return await asyncio.to_thread(_sync)


async def db_rename_cluster(cluster_id: str, new_name: str, user_id: str) -> bool:
    """Rename a face identity cluster."""
    now = datetime.now(timezone.utc).isoformat()

    def _sync():
        conn = get_connection()
        try:
            with conn:
                cursor = conn.execute(
                    """
                    UPDATE face_clusters
                    SET person_name = ?, updated_at = ?
                    WHERE cluster_id = ? AND user_id = ?
                    """,
                    (new_name, now, cluster_id, user_id),
                )
                return cursor.rowcount > 0
        finally:
            conn.close()

    return await asyncio.to_thread(_sync)


# ===============================================================
# KV Cache Operations
# ===============================================================

async def db_cache_get(key: str) -> Optional[str]:
    """Retrieve cached string value from SQLite kv_cache."""
    now = time.time()
    def _sync():
        conn = get_connection()
        try:
            row = conn.execute("SELECT value, expires_at FROM kv_cache WHERE key = ?", (key,)).fetchone()
            if not row:
                return None
            if row["expires_at"] and row["expires_at"] < now:
                conn.execute("DELETE FROM kv_cache WHERE key = ?", (key,))
                return None
            return row["value"]
        finally:
            conn.close()

    return await asyncio.to_thread(_sync)


async def db_cache_set(key: str, value: str, ttl_seconds: Optional[int] = None) -> None:
    """Store string value in SQLite kv_cache with optional TTL."""
    expires_at = time.time() + ttl_seconds if ttl_seconds else None
    def _sync():
        conn = get_connection()
        try:
            with conn:
                conn.execute(
                    """
                    INSERT INTO kv_cache (key, value, expires_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(key) DO UPDATE SET value=excluded.value, expires_at=excluded.expires_at
                    """,
                    (key, value, expires_at),
                )
        finally:
            conn.close()

    await asyncio.to_thread(_sync)


async def db_cache_delete(key: str) -> None:
    """Delete key from SQLite kv_cache."""
    def _sync():
        conn = get_connection()
        try:
            with conn:
                conn.execute("DELETE FROM kv_cache WHERE key = ?", (key,))
        finally:
            conn.close()

    await asyncio.to_thread(_sync)


# ===============================================================
# Vector Metadata Operations (Synchronous for FAISS Engine)
# ===============================================================

def sync_save_vector_metadata_batch(index_name: str, records: List[dict]) -> List[int]:
    """Insert or update metadata for a batch of vectors and return auto-increment integer IDs."""
    if not records:
        return []

    conn = get_connection()
    now = datetime.now(timezone.utc).isoformat()
    int_ids: List[int] = []

    try:
        with conn:
            for rec in records:
                vid = str(rec["id"])
                url = rec.get("url") or rec.get("metadata", {}).get("url", "")
                folder = rec.get("folder") or rec.get("metadata", {}).get("folder", "uncategorized")
                meta_json = json.dumps(rec.get("metadata", {}))

                existing = conn.execute(
                    "SELECT int_id FROM vector_metadata WHERE index_name = ? AND vector_id = ?",
                    (index_name, vid),
                ).fetchone()

                if existing:
                    int_id = existing["int_id"]
                    conn.execute(
                        """UPDATE vector_metadata
                           SET url = ?, folder = ?, metadata_json = ?, created_at = ?
                           WHERE int_id = ?""",
                        (url, folder, meta_json, now, int_id),
                    )
                else:
                    cursor = conn.execute(
                        """INSERT INTO vector_metadata (index_name, vector_id, url, folder, metadata_json, created_at)
                           VALUES (?, ?, ?, ?, ?, ?)""",
                        (index_name, vid, url, folder, meta_json, now),
                    )
                    int_id = cursor.lastrowid

                int_ids.append(int_id)
        return int_ids
    finally:
        conn.close()


def sync_get_vector_metadata_by_int_ids(index_name: str, int_ids: List[int]) -> Dict[int, dict]:
    """Fetch metadata dictionary keyed by int_id."""
    if not int_ids:
        return {}

    conn = get_connection()
    try:
        placeholders = ",".join("?" for _ in int_ids)
        rows = conn.execute(
            f"""SELECT int_id, vector_id, url, folder, metadata_json
                FROM vector_metadata
                WHERE index_name = ? AND int_id IN ({placeholders})""",
            [index_name] + list(int_ids),
        ).fetchall()

        result = {}
        for r in rows:
            try:
                meta = json.loads(r["metadata_json"])
            except Exception:
                meta = {}
            if (not meta.get("url")) and r["url"]:
                meta["url"] = r["url"]
            if (not meta.get("folder")) and r["folder"]:
                meta["folder"] = r["folder"]
            if not meta.get("url"):
                img_id = meta.get("image_id")
                if img_id:
                    pid = img_id if img_id.startswith("img_") else f"img_{img_id}"
                    fld = r["folder"] or meta.get("folder") or "general"
                    meta["url"] = f"https://res.cloudinary.com/ks28qusz/image/upload/{fld}/{pid}.jpg"

            result[r["int_id"]] = {
                "id": r["vector_id"],
                "url": meta.get("url") or r["url"],
                "folder": r["folder"],
                "metadata": meta,
            }
        return result
    finally:
        conn.close()


def sync_delete_vectors_by_ids(index_name: str, vector_ids: List[str]) -> List[int]:
    """Delete vector metadata rows by vector string IDs and return their integer IDs."""
    if not vector_ids:
        return []

    conn = get_connection()
    try:
        with conn:
            placeholders = ",".join("?" for _ in vector_ids)
            rows = conn.execute(
                f"SELECT int_id FROM vector_metadata WHERE index_name = ? AND vector_id IN ({placeholders})",
                [index_name] + list(vector_ids),
            ).fetchall()
            int_ids = [r["int_id"] for r in rows]

            if int_ids:
                del_placeholders = ",".join("?" for _ in int_ids)
                conn.execute(
                    f"DELETE FROM vector_metadata WHERE int_id IN ({del_placeholders})",
                    int_ids,
                )
            return int_ids
    finally:
        conn.close()


def sync_delete_vectors_by_url(url: str) -> Dict[str, List[int]]:
    """Delete all vector metadata matching a URL across all indexes. Returns {index_name: [int_ids]}."""
    conn = get_connection()
    try:
        with conn:
            rows = conn.execute(
                "SELECT int_id, index_name FROM vector_metadata WHERE url = ?",
                (url,),
            ).fetchall()

            res: Dict[str, List[int]] = {}
            int_ids = []
            for r in rows:
                res.setdefault(r["index_name"], []).append(r["int_id"])
                int_ids.append(r["int_id"])

            if int_ids:
                placeholders = ",".join("?" for _ in int_ids)
                conn.execute(
                    f"DELETE FROM vector_metadata WHERE int_id IN ({placeholders})",
                    int_ids,
                )
            return res
    finally:
        conn.close()


def sync_delete_vectors_by_folder(folder: str) -> Dict[str, List[int]]:
    """Delete all vector metadata matching a folder across all indexes. Returns {index_name: [int_ids]}."""
    conn = get_connection()
    try:
        with conn:
            rows = conn.execute(
                "SELECT int_id, index_name FROM vector_metadata WHERE folder = ?",
                (folder,),
            ).fetchall()

            res: Dict[str, List[int]] = {}
            int_ids = []
            for r in rows:
                res.setdefault(r["index_name"], []).append(r["int_id"])
                int_ids.append(r["int_id"])

            if int_ids:
                placeholders = ",".join("?" for _ in int_ids)
                conn.execute(
                    f"DELETE FROM vector_metadata WHERE int_id IN ({placeholders})",
                    int_ids,
                )
            return res
    finally:
        conn.close()


def sync_get_folder_image_count(folder: str) -> int:
    """Returns number of indexed vector records belonging to a folder."""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT COUNT(*) FROM vector_metadata WHERE folder = ?",
            (folder,)
        ).fetchone()
        return row[0] if row else 0
    finally:
        conn.close()


def sync_list_all_indexed_folders() -> List[str]:
    """Returns distinct folder names currently indexed."""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT DISTINCT folder FROM vector_metadata WHERE folder IS NOT NULL AND folder != ''"
        ).fetchall()
        return [r[0] for r in rows]
    finally:
        conn.close()


def sync_get_all_vector_metadata(index_name: str, limit: int = 10000) -> List[dict]:
    """Retrieve all vector metadata records for an index."""
    conn = get_connection()
    try:
        rows = conn.execute(
            """SELECT int_id, vector_id, url, folder, metadata_json
               FROM vector_metadata
               WHERE index_name = ?
               LIMIT ?""",
            (index_name, limit),
        ).fetchall()

        results = []
        for r in rows:
            try:
                meta = json.loads(r["metadata_json"])
            except Exception:
                meta = {}
            results.append({
                "int_id": r["int_id"],
                "id": r["vector_id"],
                "url": r["url"],
                "folder": r["folder"],
                "metadata": meta,
            })
        return results
    finally:
        conn.close()


def sync_clear_vector_metadata(index_name: Optional[str] = None):
    """Clear vector metadata for a single index or completely."""
    conn = get_connection()
    try:
        with conn:
            if index_name:
                conn.execute("DELETE FROM vector_metadata WHERE index_name = ?", (index_name,))
            else:
                conn.execute("DELETE FROM vector_metadata")
    finally:
        conn.close()


class SQLiteRepository:
    """Unified repository interface for SQLite database operations."""

    def __init__(self):
        init_database()

    def get_user_by_username(self, username: str) -> Optional[Dict[str, Any]]:
        conn = get_connection()
        try:
            row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def get_user_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        conn = get_connection()
        try:
            row = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def get_user_by_id(self, user_id: str) -> Optional[Dict[str, Any]]:
        conn = get_connection()
        try:
            row = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def create_user(
        self,
        user_id: str,
        username: str,
        email: str,
        hashed_password: str,
        role: str = "user",
        cloudinary_url: Optional[str] = None
    ) -> bool:
        now = datetime.now(timezone.utc).isoformat()
        conn = get_connection()
        try:
            with conn:
                conn.execute(
                    "INSERT INTO users (user_id, username, email, hashed_password, role, cloudinary_url, created_at, last_seen) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (user_id, username, email, hashed_password, role, cloudinary_url, now, now)
                )
            return True
        except Exception:
            return False
        finally:
            conn.close()

    def update_user_cloudinary_url(self, user_id: str, cloudinary_url: str) -> bool:
        now = datetime.now(timezone.utc).isoformat()
        conn = get_connection()
        try:
            with conn:
                cursor = conn.execute(
                    "UPDATE users SET cloudinary_url = ?, last_seen = ? WHERE user_id = ?",
                    (cloudinary_url, now, user_id)
                )
                return cursor.rowcount > 0
        finally:
            conn.close()

    def create_job(self, job_id: str, total_images: int = 0, user_id: str = "anonymous", folder: str = "default") -> None:
        now = datetime.now(timezone.utc).isoformat()
        conn = get_connection()
        try:
            with conn:
                conn.execute(
                    "INSERT INTO upload_jobs (job_id, user_id, folder, status, total_files, processed_files, created_at, updated_at) VALUES (?, ?, ?, 'processing', ?, 0, ?, ?)",
                    (job_id, user_id, folder, total_images, now, now)
                )
        finally:
            conn.close()

    def update_job(self, job_id: str, processed_images: int, status: str = "completed", error: Optional[str] = None) -> None:
        now = datetime.now(timezone.utc).isoformat()
        conn = get_connection()
        try:
            with conn:
                conn.execute(
                    "UPDATE upload_jobs SET processed_files = ?, status = ?, error = ?, updated_at = ? WHERE job_id = ?",
                    (processed_images, status, error, now, job_id)
                )
        finally:
            conn.close()

    def get_job_by_id(self, job_id: str) -> Optional[Dict[str, Any]]:
        conn = get_connection()
        try:
            row = conn.execute("SELECT * FROM upload_jobs WHERE job_id = ?", (job_id,)).fetchone()
            if not row:
                return None
            logs = []
            if "logs" in row.keys() and row["logs"]:
                try:
                    logs = json.loads(row["logs"])
                except Exception:
                    logs = [row["logs"]]
            return {
                "job_id": row["job_id"],
                "status": row["status"],
                "total_images": row["total_files"],
                "processed_images": row["processed_files"],
                "total_files": row["total_files"],
                "processed_files": row["processed_files"],
                "current_stage": row["status"],
                "logs": logs,
                "error_message": row["error"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"]
            }
        finally:
            conn.close()

    def append_job_log(self, job_id: str, message: str) -> None:
        conn = get_connection()
        try:
            with conn:
                row = conn.execute("SELECT logs FROM upload_jobs WHERE job_id = ?", (job_id,)).fetchone()
                existing = []
                if row and row["logs"]:
                    try:
                        existing = json.loads(row["logs"])
                    except Exception:
                        pass
                existing.append(message)
                conn.execute("UPDATE upload_jobs SET logs = ? WHERE job_id = ?", (json.dumps(existing), job_id))
        finally:
            conn.close()

    def save_face_cluster(
        self,
        cluster_id: str,
        person_name: str,
        face_count: int,
        sample_crop_urls: List[str],
        user_id: str = "system",
        folder: Optional[str] = None
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        rep_url = sample_crop_urls[0] if sample_crop_urls else ""
        conn = get_connection()
        try:
            with conn:
                conn.execute(
                    """
                    INSERT INTO face_clusters (cluster_id, user_id, folder, person_name, representative_face_url, face_count, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(cluster_id) DO UPDATE SET
                        folder=excluded.folder,
                        person_name=excluded.person_name,
                        representative_face_url=excluded.representative_face_url,
                        face_count=excluded.face_count,
                        updated_at=excluded.updated_at
                    """,
                    (cluster_id, user_id, folder, person_name, rep_url, face_count, now)
                )
        finally:
            conn.close()

    def get_all_face_clusters(self, folder: Optional[str] = None, user_id: Optional[str] = None) -> List[Dict[str, Any]]:
        conn = get_connection()
        try:
            query = "SELECT * FROM face_clusters"
            params = []
            conditions = []
            if folder:
                conditions.append("folder = ?")
                params.append(folder)
            if user_id and user_id != "system":
                conditions.append("(user_id = ? OR user_id = 'system')")
                params.append(user_id)

            if conditions:
                query += " WHERE " + " AND ".join(conditions)
            query += " ORDER BY face_count DESC"

            rows = conn.execute(query, tuple(params)).fetchall()
            return [
                {
                    "cluster_id": r["cluster_id"],
                    "person_name": r["person_name"] or "Unnamed Person",
                    "face_count": r["face_count"],
                    "folder": r["folder"],
                    "medoid_cloudinary_url": r["medoid_cloudinary_url"] if "medoid_cloudinary_url" in r.keys() else None,
                    "sample_crop_urls": [r["representative_face_url"]] if r["representative_face_url"] else [],
                    "created_at": r["updated_at"]
                }
                for r in rows
            ]
        finally:
            conn.close()

    def update_cluster_name(self, cluster_id: str, new_name: str) -> bool:
        now = datetime.now(timezone.utc).isoformat()
        conn = get_connection()
        try:
            with conn:
                cursor = conn.execute(
                    "UPDATE face_clusters SET person_name = ?, updated_at = ? WHERE cluster_id = ?",
                    (new_name, now, cluster_id)
                )
                return cursor.rowcount > 0
        finally:
            conn.close()


_repo_instance: Optional[SQLiteRepository] = None


def get_repository() -> SQLiteRepository:
    global _repo_instance
    if _repo_instance is None:
        _repo_instance = SQLiteRepository()
    return _repo_instance


