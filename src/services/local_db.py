"""
src/services/local_db.py — High-performance, zero-dependency local SQLite database.
Replaces Supabase and Upstash Redis with a persistent local SQLite database.
Stores users (UUID), background upload jobs, face clustering albums, and key-value cache.
"""
import asyncio
import json
import os
import sqlite3
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

DB_DIR = os.path.join(os.getcwd(), "data")
DB_PATH = os.path.join(DB_DIR, "local_storage.db")


def _get_connection() -> sqlite3.Connection:
    """Create a thread-safe connection to the local SQLite database."""
    os.makedirs(DB_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    return conn


def _init_db():
    """Initialize SQLite tables for users, jobs, clusters, and cache."""
    conn = _get_connection()
    try:
        with conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id TEXT PRIMARY KEY,
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

            # Migration check: ensure 'logs' column exists in existing upload_jobs tables
            cols = [row[1] for row in conn.execute("PRAGMA table_info(upload_jobs)").fetchall()]
            if "logs" not in cols:
                conn.execute("ALTER TABLE upload_jobs ADD COLUMN logs TEXT DEFAULT '[]'")
    finally:
        conn.close()


# Initialize schema on module import
_init_db()


# ──────────────────────────────────────────────────────────────
# User Management (UUID persistence)
# ──────────────────────────────────────────────────────────────
def sync_get_or_create_user(user_id: Optional[str] = None) -> str:
    """Validate or generate a persistent UUID for the user."""
    conn = _get_connection()
    now = datetime.now(timezone.utc).isoformat()
    try:
        uid = (user_id or "").strip()
        if not uid:
            uid = uuid.uuid4().hex

        with conn:
            row = conn.execute("SELECT user_id FROM users WHERE user_id = ?", (uid,)).fetchone()
            if row:
                conn.execute("UPDATE users SET last_seen = ? WHERE user_id = ?", (now, uid))
            else:
                conn.execute(
                    "INSERT INTO users (user_id, created_at, last_seen) VALUES (?, ?, ?)",
                    (uid, now, now),
                )
        return uid
    finally:
        conn.close()


async def get_or_create_user(user_id: Optional[str] = None) -> str:
    """Async wrapper for user registration."""
    return await asyncio.to_thread(sync_get_or_create_user, user_id)


# ──────────────────────────────────────────────────────────────
# Upload Jobs (Replaces Supabase upload_jobs)
# ──────────────────────────────────────────────────────────────
def sync_create_job(
    job_id: str,
    user_id: str,
    folder: str,
    total_files: int,
    payload: Optional[dict] = None,
) -> None:
    conn = _get_connection()
    now = datetime.now(timezone.utc).isoformat()
    ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
    initial_logs = json.dumps([f"[{ts}] Job queued: {total_files} files scheduled for folder '{folder}'"])
    try:
        with conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO upload_jobs (
                    job_id, user_id, folder, status, total_files, processed_files,
                    payload, logs, created_at, updated_at
                ) VALUES (?, ?, ?, 'pending', ?, 0, ?, ?, ?, ?)
                """,
                (
                    job_id,
                    user_id or "anonymous",
                    folder,
                    total_files,
                    json.dumps(payload) if payload else None,
                    initial_logs,
                    now,
                    now,
                ),
            )
    finally:
        conn.close()


def sync_get_job(job_id: str) -> Optional[dict]:
    conn = _get_connection()
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
                d["logs"] = [d["logs"]]
        else:
            d["logs"] = []
        return d
    finally:
        conn.close()


def sync_append_job_log(job_id: str, message: str) -> None:
    """Appends a timestamped log entry to the job's log trail in local SQLite."""
    conn = _get_connection()
    now = datetime.now(timezone.utc).isoformat()
    ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
    entry = f"[{ts}] {message}"
    try:
        with conn:
            row = conn.execute("SELECT logs FROM upload_jobs WHERE job_id = ?", (job_id,)).fetchone()
            if row:
                logs = []
                if row["logs"]:
                    try:
                        logs = json.loads(row["logs"])
                    except Exception:
                        logs = [row["logs"]]
                logs.append(entry)
                conn.execute(
                    "UPDATE upload_jobs SET logs = ?, updated_at = ? WHERE job_id = ?",
                    (json.dumps(logs), now, job_id),
                )
    finally:
        conn.close()


async def db_append_job_log(job_id: str, message: str) -> None:
    """Async wrapper to append a log message to a job."""
    await asyncio.to_thread(sync_append_job_log, job_id, message)


def sync_update_job(job_id: str, patch: dict) -> bool:
    conn = _get_connection()
    now = datetime.now(timezone.utc).isoformat()
    try:
        fields = []
        values = []
        for k, v in patch.items():
            if k in ("result", "payload") and isinstance(v, (dict, list)):
                v = json.dumps(v)
            fields.append(f"{k} = ?")
            values.append(v)

        fields.append("updated_at = ?")
        values.append(now)
        values.append(job_id)

        sql = f"UPDATE upload_jobs SET {', '.join(fields)} WHERE job_id = ?"
        with conn:
            cursor = conn.execute(sql, tuple(values))
            return cursor.rowcount > 0
    finally:
        conn.close()


async def db_create_job(job_id: str, user_id: str, folder: str, total_files: int, payload: dict = None) -> None:
    await asyncio.to_thread(sync_create_job, job_id, user_id, folder, total_files, payload)


async def db_get_job(job_id: str) -> Optional[dict]:
    return await asyncio.to_thread(sync_get_job, job_id)


async def db_update_job(job_id: str, patch: dict) -> bool:
    return await asyncio.to_thread(sync_update_job, job_id, patch)


# ──────────────────────────────────────────────────────────────
# Local Key-Value Store & Cache (Replaces Upstash Redis)
# ──────────────────────────────────────────────────────────────
def sync_kv_set(key: str, value: Any, ttl: Optional[int] = None) -> None:
    conn = _get_connection()
    expires_at = (time.time() + ttl) if ttl else None
    val_str = json.dumps(value) if not isinstance(value, str) else value
    try:
        with conn:
            conn.execute(
                "INSERT OR REPLACE INTO kv_cache (key, value, expires_at) VALUES (?, ?, ?)",
                (key, val_str, expires_at),
            )
    finally:
        conn.close()


def sync_kv_get(key: str) -> Optional[Any]:
    conn = _get_connection()
    now = time.time()
    try:
        row = conn.execute("SELECT value, expires_at FROM kv_cache WHERE key = ?", (key,)).fetchone()
        if not row:
            return None
        if row["expires_at"] and row["expires_at"] < now:
            with conn:
                conn.execute("DELETE FROM kv_cache WHERE key = ?", (key,))
            return None
        val = row["value"]
        try:
            return json.loads(val)
        except Exception:
            return val
    finally:
        conn.close()


def sync_kv_incr(key: str) -> int:
    conn = _get_connection()
    try:
        with conn:
            row = conn.execute("SELECT value FROM kv_cache WHERE key = ?", (key,)).fetchone()
            if row:
                try:
                    curr = int(row["value"])
                except Exception:
                    curr = 0
                new_val = curr + 1
                conn.execute("UPDATE kv_cache SET value = ? WHERE key = ?", (str(new_val), key))
                return new_val
            else:
                conn.execute(
                    "INSERT INTO kv_cache (key, value, expires_at) VALUES (?, '1', NULL)",
                    (key,),
                )
                return 1
    finally:
        conn.close()


def sync_kv_delete(key: str) -> None:
    conn = _get_connection()
    try:
        with conn:
            conn.execute("DELETE FROM kv_cache WHERE key = ?", (key,))
    finally:
        conn.close()


async def local_cache_set(key: str, value: Any, ttl: Optional[int] = None) -> None:
    await asyncio.to_thread(sync_kv_set, key, value, ttl)


async def local_cache_get(key: str) -> Optional[Any]:
    return await asyncio.to_thread(sync_kv_get, key)


async def local_cache_incr(key: str) -> int:
    return await asyncio.to_thread(sync_kv_incr, key)


async def local_cache_delete(key: str) -> None:
    await asyncio.to_thread(sync_kv_delete, key)


# ──────────────────────────────────────────────────────────────
# Face Clustering Storage (Replaces Supabase clustering tables)
# ──────────────────────────────────────────────────────────────
def sync_save_clusters(user_id: str, cluster_rows: List[dict], vector_rows: List[dict]) -> None:
    conn = _get_connection()
    now = datetime.now(timezone.utc).isoformat()
    try:
        with conn:
            conn.execute("DELETE FROM face_clusters WHERE user_id = ?", (user_id,))
            conn.execute("DELETE FROM face_vector_clusters WHERE user_id = ?", (user_id,))

            for c in cluster_rows:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO face_clusters (
                        cluster_id, user_id, person_name, representative_face_url,
                        face_count, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        c["cluster_id"],
                        user_id,
                        c.get("person_name", f"Person {c['cluster_id']}"),
                        c.get("representative_face_url", ""),
                        c.get("face_count", 0),
                        now,
                    ),
                )

            for v in vector_rows:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO face_vector_clusters (
                        vector_id, user_id, cluster_id, image_url, folder
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        v["vector_id"],
                        user_id,
                        v["cluster_id"],
                        v.get("image_url", ""),
                        v.get("folder", ""),
                    ),
                )
    finally:
        conn.close()


def sync_get_clusters(user_id: str) -> List[dict]:
    conn = _get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM face_clusters WHERE user_id = ? ORDER BY face_count DESC",
            (user_id,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def sync_get_cluster_images(user_id: str, cluster_id: str) -> List[dict]:
    conn = _get_connection()
    try:
        rows = conn.execute(
            "SELECT vector_id, image_url, folder FROM face_vector_clusters WHERE user_id = ? AND cluster_id = ?",
            (user_id, cluster_id),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def sync_rename_cluster(user_id: str, cluster_id: str, person_name: str) -> bool:
    conn = _get_connection()
    now = datetime.now(timezone.utc).isoformat()
    try:
        with conn:
            cursor = conn.execute(
                "UPDATE face_clusters SET person_name = ?, updated_at = ? WHERE user_id = ? AND cluster_id = ?",
                (person_name, now, user_id, cluster_id),
            )
            return cursor.rowcount > 0
    finally:
        conn.close()


async def db_save_clusters(user_id: str, cluster_rows: List[dict], vector_rows: List[dict]) -> None:
    await asyncio.to_thread(sync_save_clusters, user_id, cluster_rows, vector_rows)


async def db_get_clusters(user_id: str) -> List[dict]:
    return await asyncio.to_thread(sync_get_clusters, user_id)


async def db_get_cluster_images(user_id: str, cluster_id: str) -> List[dict]:
    return await asyncio.to_thread(sync_get_cluster_images, user_id, cluster_id)


async def db_rename_cluster(user_id: str, cluster_id: str, person_name: str) -> bool:
    return await asyncio.to_thread(sync_rename_cluster, user_id, cluster_id, person_name)


# ──────────────────────────────────────────────────────────────
# Vector Metadata Management (For FAISS ID-Mapping & Metadata)
# ──────────────────────────────────────────────────────────────
def sync_save_vector_metadata_batch(index_name: str, records: List[dict]) -> List[int]:
    """
    Saves or replaces vector metadata and returns the integer ID for each vector.
    records = [{'id': str, 'url': str, 'folder': str, 'metadata': dict}, ...]
    """
    if not records:
        return []

    conn = _get_connection()
    now = datetime.now(timezone.utc).isoformat()
    int_ids: List[int] = []

    try:
        with conn:
            for rec in records:
                vid = str(rec["id"])
                url = rec.get("url") or rec.get("metadata", {}).get("url", "")
                folder = rec.get("folder") or rec.get("metadata", {}).get("folder", "uncategorized")
                meta_json = json.dumps(rec.get("metadata", {}))

                # Check if already exists in this index
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

    conn = _get_connection()
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
            if "url" not in meta and r["url"]:
                meta["url"] = r["url"]
            if "folder" not in meta and r["folder"]:
                meta["folder"] = r["folder"]

            result[r["int_id"]] = {
                "id": r["vector_id"],
                "url": r["url"],
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

    conn = _get_connection()
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
    conn = _get_connection()
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
    conn = _get_connection()
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


def sync_get_all_vector_metadata(index_name: str, limit: int = 10000) -> List[dict]:
    """Retrieve all vector metadata records for an index."""
    conn = _get_connection()
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
    conn = _get_connection()
    try:
        with conn:
            if index_name:
                conn.execute("DELETE FROM vector_metadata WHERE index_name = ?", (index_name,))
            else:
                conn.execute("DELETE FROM vector_metadata")
    finally:
        conn.close()

