"""
scripts/test_ingest_and_search.py — End-to-End Ingestion & Search Testing Script.

Performs:
1. API Health Check.
2. Ingests 50 photos into a target folder (from a local directory OR auto-generated sample JPEGs).
3. Processes all images into FAISS vector indices.
4. Optionally triggers face clustering into people albums.
5. Executes visual search queries with folder scoping and prints similarity scores.

Usage:
    # Auto-generate 50 test images and run test:
    python scripts/test_ingest_and_search.py --auto-generate

    # Use your own folder of 50 images:
    python scripts/test_ingest_and_search.py --images-dir /path/to/my/50_photos --folder-name my_album
"""
import argparse
import io
import os
import sys
import time
import requests
from PIL import Image, ImageDraw

BASE_URL = os.getenv("API_BASE_URL", "http://127.0.0.1:7860")


def generate_sample_image(index: int) -> bytes:
    """Generate a distinct test image with color and text."""
    colors = [(180, 50, 50), (50, 180, 50), (50, 50, 180), (200, 150, 50), (150, 50, 200)]
    bg_color = colors[index % len(colors)]
    img = Image.new("RGB", (300, 300), color=bg_color)
    draw = ImageDraw.Draw(img)
    draw.rectangle([50, 50, 250, 250], outline=(255, 255, 255), width=3)
    draw.text((70, 130), f"Photo #{index + 1}", fill=(255, 255, 255))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=90)
    return buf.getvalue()


def step1_health_check():
    print("\n[Step 1/5] Checking API Health...")
    try:
        r = requests.get(f"{BASE_URL}/api/health", timeout=5)
        r.raise_for_status()
        print(" -> API is healthy:", r.json())
    except Exception as e:
        print(f" -> ERROR: Cannot reach API at {BASE_URL}: {e}")
        sys.exit(1)


def step2_upload_50_images(images_dir: str | None, folder_name: str, count: int = 50) -> list[str]:
    print(f"\n[Step 2/5] Uploading {count} images to folder '{folder_name}'...")
    image_ids = []

    files_to_send = []
    if images_dir and os.path.isdir(images_dir):
        valid_exts = (".jpg", ".jpeg", ".png", ".webp")
        paths = [
            os.path.join(images_dir, f) for f in sorted(os.listdir(images_dir))
            if f.lower().endswith(valid_exts)
        ][:count]
        print(f" -> Loaded {len(paths)} local images from '{images_dir}'")
        for p in paths:
            files_to_send.append(("files", (os.path.basename(p), open(p, "rb"), "image/jpeg")))
    else:
        print(f" -> Auto-generating {count} test images...")
        for i in range(count):
            img_bytes = generate_sample_image(i)
            files_to_send.append(("files", (f"sample_photo_{i+1:03d}.jpg", img_bytes, "image/jpeg")))

    start_time = time.time()
    resp = requests.post(
        f"{BASE_URL}/api/upload/batch",
        files=files_to_send,
        data={"folder_name": folder_name},
        timeout=180,
    )
    duration = time.time() - start_time
    resp.raise_for_status()
    body = resp.json()

    successful = body.get("successful", 0)
    print(f" -> Batch upload finished in {duration:.2f}s: {successful}/{body.get('total')} photos saved.")
    
    for item in body.get("items", []):
        if item.get("status") == "success":
            image_ids.append(item.get("image_id"))

    return image_ids


def step3_process_images(image_ids: list[str]):
    print(f"\n[Step 3/5] Processing {len(image_ids)} images into FAISS vector indices...")
    success_count = 0
    start_time = time.time()

    for i, img_id in enumerate(image_ids, 1):
        try:
            r = requests.post(f"{BASE_URL}/api/process/image/{img_id}", timeout=30)
            if r.status_code == 200:
                res = r.json()
                success_count += 1
                if i % 10 == 0 or i == len(image_ids):
                    print(f"    Processed {i}/{len(image_ids)} (faces: {res.get('faces_detected')}, objects: {res.get('objects_detected')})")
        except Exception as e:
            print(f"    Failed processing {img_id}: {e}")

    total_time = time.time() - start_time
    avg_per_img = total_time / max(1, len(image_ids))
    print(f" -> Completed AI feature extraction in {total_time:.2f}s (~{avg_per_img*1000:.1f}ms per image)")


def step4_cluster_faces():
    print("\n[Step 4/5] Running Face Clustering to group identities into albums...")
    try:
        r = requests.post(f"{BASE_URL}/api/clusters/generate?min_cluster_size=2", timeout=30)
        print(" -> Clustering result:", r.json())
        clusters_resp = requests.get(f"{BASE_URL}/api/clusters", timeout=10)
        clusters = clusters_resp.json()
        print(f" -> Total discovered albums/clusters: {len(clusters)}")
        for c in clusters[:5]:
            print(f"    Cluster {c.get('cluster_id')}: {c.get('person_name', 'Unnamed')} ({c.get('face_count')} faces)")
    except Exception as e:
        print(f" -> Clustering error: {e}")


def step5_search_images(folder_name: str, query_image_bytes: bytes):
    print(f"\n[Step 5/5] Executing Visual Searches...")

    # A. Scoped Search within the folder
    print(f" -> Test A: Scoped search inside folder '{folder_name}'...")
    start_time = time.time()
    files = {"file": ("query.jpg", query_image_bytes, "image/jpeg")}
    r_scoped = requests.post(
        f"{BASE_URL}/api/search/image?top_k=5",
        files=files,
        data={"folder_name": folder_name},
        timeout=15,
    )
    dur_a = time.time() - start_time
    r_scoped.raise_for_status()
    res_a = r_scoped.json()
    print(f"    Search took {dur_a*1000:.1f}ms. Query type: '{res_a.get('query_type')}'. Found {res_a.get('total_matches')} matches.")
    for idx, match in enumerate(res_a.get("results", [])[:5], 1):
        print(f"    {idx}. Image: {match.get('image_id')} | Score: {match.get('score'):.4f} | Folder: {match.get('metadata', {}).get('folder')}")

    # B. Global Search across all folders
    print(f"\n -> Test B: Global search across all gallery folders...")
    start_time = time.time()
    files = {"file": ("query.jpg", query_image_bytes, "image/jpeg")}
    r_global = requests.post(
        f"{BASE_URL}/api/search/image?top_k=5",
        files=files,
        timeout=15,
    )
    dur_b = time.time() - start_time
    r_global.raise_for_status()
    res_b = r_global.json()
    print(f"    Search took {dur_b*1000:.1f}ms. Found {res_b.get('total_matches')} matches.")


def main():
    parser = argparse.ArgumentParser(description="Test Ingest 50 Images and Visual Search")
    parser.add_argument("--images-dir", type=str, default=None, help="Path to local folder containing images")
    parser.add_argument("--folder-name", type=str, default="test_album_50", help="Target Cloudinary/gallery album name")
    parser.add_argument("--count", type=int, default=50, help="Number of images to ingest (default: 50)")
    parser.add_argument("--auto-generate", action="store_true", help="Auto-generate synthetic test images")
    args = parser.parse_args()

    step1_health_check()
    image_ids = step2_upload_50_images(args.images_dir, args.folder_name, count=args.count)
    if not image_ids:
        print("ERROR: No images were successfully uploaded.")
        return

    step3_process_images(image_ids)
    step4_cluster_faces()

    # Create a query image (use first photo with face if images_dir provided, otherwise generate sample)
    query_bytes = None
    if args.images_dir and os.path.isdir(args.images_dir):
        valid_exts = (".jpg", ".jpeg", ".png", ".webp")
        first_img = next(
            (os.path.join(args.images_dir, f) for f in sorted(os.listdir(args.images_dir)) if f.lower().endswith(valid_exts)),
            None
        )
        if first_img:
            print(f"\n -> Using real query image for search: {os.path.basename(first_img)}")
            with open(first_img, "rb") as qf:
                query_bytes = qf.read()

    if not query_bytes:
        query_bytes = generate_sample_image(0)

    step5_search_images(args.folder_name, query_bytes)

    print("\n✅ End-to-End Test Completed Successfully!")


if __name__ == "__main__":
    main()

