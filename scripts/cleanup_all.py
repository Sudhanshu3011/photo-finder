"""
scripts/cleanup_all.py — Complete cleanup script for AWS S3 and FAISS vector stores.

Cleans up:
1. AWS S3: deletes all uploaded assets across tenant prefixes.
2. FAISS vector storage: wipes all .index files and re-initializes empty stores.
3. Database metadata: clears vector_metadata and related tables.
4. Local image cache: clears saved_images/ directory.
"""
import os
import shutil
from src.core.config import FAISS_DATA_DIR
from src.modules.infra.faiss_engine import vector_engine
from src.modules.infra.postgres_repository import sync_clear_vector_metadata
from src.modules.storage.s3_storage import get_s3_bucket, delete_s3_folder, list_s3_objects, delete_s3_object

def cleanup_s3():
    print("\n[1/4] Cleaning AWS S3 Object Storage...")
    bucket = get_s3_bucket()
    if not bucket:
        print(" -> No AWS S3 bucket configured. Skipping S3 cleanup.")
        return

    try:
        objects = list_s3_objects(prefix="", bucket=bucket, max_keys=1000)
        print(f" -> Found {len(objects)} objects in bucket '{bucket}' to clean up.")
        for obj in objects:
            key = obj.get("key")
            if key:
                delete_s3_object(key=key, bucket=bucket)
        print(" -> S3 cleanup completed.")
    except Exception as e:
        print(f" -> Error during S3 cleanup: {e}")

# Backward compatibility alias
cleanup_cloudinary = cleanup_s3


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


def cleanup_database_metadata():
    print("\n[3/4] Cleaning vector metadata and database records...")
    try:
        sync_clear_vector_metadata()
        print(" -> Vector metadata cleared successfully.")
    except Exception as e:
        print(f" -> Could not clear metadata: {e}")


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
    cleanup_s3()
    cleanup_faiss()
    cleanup_database_metadata()
    cleanup_local_cache()
    print("\n✅ FAISS AND AWS S3 CLEANUP COMPLETED SUCCESSFULLY!\n")

