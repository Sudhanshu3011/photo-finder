"""
scripts/cleanup_all.py — Complete cleanup script for Cloudinary and FAISS vector stores.

Cleans up:
1. Cloudinary: deletes all uploaded assets across all folders, then deletes the folders.
2. FAISS vector storage: wipes all .index files and re-initializes empty stores.
3. SQLite metadata: clears vector_metadata, face_clusters, face_vector_clusters, upload_jobs, and kv_cache.
4. Local image cache: clears saved_images/ directory.
"""
import os
import shutil
import sqlite3
import cloudinary
import cloudinary.api
import cloudinary.uploader
from src.core.config import DEFAULT_CLOUDINARY_URL, FAISS_DATA_DIR
from src.modules.infra.faiss_engine import vector_engine

def cleanup_cloudinary():
    print("\n[1/4] Cleaning Cloudinary...")
    if not DEFAULT_CLOUDINARY_URL:
        print(" -> No DEFAULT_CLOUDINARY_URL configured. Skipping Cloudinary cleanup.")
        return

    cloudinary.config(cloudinary_url=DEFAULT_CLOUDINARY_URL)

    # 1. List and delete resources folder by folder
    try:
        root_folders_resp = cloudinary.api.root_folders()
        folders = [f["name"] for f in root_folders_resp.get("folders", [])]
        print(f" -> Discovered root folders: {folders}")
        for folder in folders:
            print(f"    Deleting resources in folder '{folder}'...")
            try:
                cloudinary.api.delete_resources_by_prefix(f"{folder}/")
            except Exception as e:
                print(f"    Warning deleting prefix {folder}/: {e}")
            try:
                cloudinary.api.delete_folder(folder)
                print(f"    Deleted folder '{folder}'")
            except Exception as e:
                print(f"    Note on deleting folder '{folder}': {e}")
    except Exception as e:
        print(f" -> Error inspecting root folders: {e}")

    # 2. Delete any leftover upload resources (e.g. at root level)
    while True:
        try:
            res = cloudinary.api.resources(type="upload", max_results=500)
            items = res.get("resources", [])
            if not items:
                print(" -> All Cloudinary upload resources successfully deleted.")
                break
            public_ids = [item["public_id"] for item in items]
            print(f"    Deleting batch of {len(public_ids)} remaining resources...")
            cloudinary.api.delete_resources(public_ids)
        except Exception as e:
            print(f" -> Error during batch resource deletion: {e}")
            break

    # 3. Final verification
    try:
        check = cloudinary.api.resources(type="upload", max_results=10)
        remaining = len(check.get("resources", []))
        print(f" -> Final Cloudinary verification: {remaining} remaining resources.")
    except Exception as e:
        print(f" -> Verification error: {e}")


def cleanup_faiss():
    print("\n[2/4] Cleaning FAISS Vector Engine...")
    try:
        vector_engine.reset_all()
        print(" -> vector_engine.reset_all() called successfully.")
    except Exception as e:
        print(f" -> Warning resetting vector engine: {e}")

    faiss_dir = os.path.join(os.getcwd(), FAISS_DATA_DIR)
    if os.path.exists(faiss_dir):
        for f in os.listdir(faiss_dir):
            if f.endswith(".index"):
                try:
                    os.remove(os.path.join(faiss_dir, f))
                    print(f"    Deleted index file: {f}")
                except Exception as e:
                    print(f"    Failed removing {f}: {e}")

    # Re-initialize clean empty indices
    vector_engine._init_indices()
    for name, idx in vector_engine.indices.items():
        print(f"    Verified clean index '{name}': ntotal={idx.ntotal}")


def cleanup_sqlite_metadata():
    print("\n[3/4] Cleaning SQLite database metadata...")
    db_paths = ["data/local_storage.db", "/app/data/local_storage.db"]
    target_db = next((p for p in db_paths if os.path.exists(p)), None)

    if not target_db:
        print(" -> SQLite database file not found. Skipping.")
        return

    conn = sqlite3.connect(target_db)
    cursor = conn.cursor()
    tables_to_clear = [
        "vector_metadata",
        "face_clusters",
        "face_vector_clusters",
        "upload_jobs",
        "kv_cache",
    ]

    for table in tables_to_clear:
        try:
            cursor.execute(f"DELETE FROM {table}")
            print(f"    Cleared table: {table}")
        except Exception as e:
            print(f"    Could not clear table {table}: {e}")

    conn.commit()
    conn.close()
    print(" -> SQLite metadata tables cleared successfully.")


def cleanup_local_cache():
    print("\n[4/4] Cleaning local image caches...")
    cache_dirs = ["saved_images", "/app/saved_images"]
    for c_dir in cache_dirs:
        if os.path.exists(c_dir):
            for item in os.listdir(c_dir):
                item_path = os.path.join(c_dir, item)
                try:
                    if os.path.isdir(item_path):
                        shutil.rmtree(item_path)
                    else:
                        os.remove(item_path)
                    print(f"    Removed cached item: {item_path}")
                except Exception as e:
                    print(f"    Error removing {item_path}: {e}")
    print(" -> Local saved_images cache cleared.")


if __name__ == "__main__":
    print("=== STARTING COMPLETE CLEANUP ===")
    cleanup_cloudinary()
    cleanup_faiss()
    cleanup_sqlite_metadata()
    cleanup_local_cache()
    print("\n✅ FAISS AND CLOUDINARY CLEANUP COMPLETED SUCCESSFULLY!\n")

