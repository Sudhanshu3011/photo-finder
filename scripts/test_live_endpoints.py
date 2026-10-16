"""
scripts/test_live_endpoints.py — Live End-to-End Endpoint Verification Script.

Tests every core API endpoint against a running Visual Search API instance:
1. GET  /api/health            - Health check & readiness probe
2. POST /api/auth/register     - Multi-tenant user registration & JWT token generation
3. POST /api/auth/login        - User login verification
4. POST /api/upload/photo      - Multipart single photo upload
5. POST /api/process/image/{id}- AI inference (Vision & Face Embeddings)
6. POST /api/search/image      - Vector similarity search
7. POST /api/log               - Telemetry & logging ingestion
"""
import io
import sys
import time
import requests
import numpy as np
from PIL import Image

BASE_URL = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:7860"

def create_synthetic_image_bytes():
    """Create a synthetic 300x300 RGB image with colored shapes."""
    arr = np.zeros((300, 300, 3), dtype=np.uint8)
    arr[:, :150] = [200, 50, 50]    # Reddish left half
    arr[:, 150:] = [50, 150, 220]   # Bluish right half
    img = Image.fromarray(arr)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=90)
    buf.seek(0)
    return buf.getvalue()

def run_all_tests():
    print(f"=== Starting Visual Search API Live Endpoint Verification ===")
    print(f"Target Base URL: {BASE_URL}\n")
    passed = 0
    total = 0

    # 1. Health check
    total += 1
    print(f"[{total}] Testing GET /api/health ...")
    r = requests.get(f"{BASE_URL}/api/health", timeout=10)
    assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
    health_data = r.json()
    assert health_data.get("status") == "ok", f"Health status not ok: {health_data}"
    print(f"    -> PASSED! Status: {health_data['status']}, Version: {health_data.get('version')}")
    passed += 1

    # 2. Register User & Tenant
    total += 1
    ts = int(time.time())
    test_user = f"tester_{ts}"
    test_email = f"tester_{ts}@example.com"
    test_password = "SecurePassword123!"
    tenant_id = f"tenant_{ts}"
    print(f"\n[{total}] Testing POST /api/auth/register (Tenant: {tenant_id}, User: {test_user}) ...")
    r = requests.post(
        f"{BASE_URL}/api/auth/register",
        json={
            "username": test_user,
            "email": test_email,
            "password": test_password,
            "tenant_id": tenant_id,
            "role": "user"
        },
        timeout=10
    )
    assert r.status_code == 201, f"Expected 201, got {r.status_code}: {r.text}"
    auth_data = r.json()
    token = auth_data.get("access_token")
    user_id = auth_data.get("user_id")
    assert token and user_id, f"Missing token or user_id in response: {auth_data}"
    print(f"    -> PASSED! User ID: {user_id}, Tenant: {auth_data.get('tenant_id')}")
    passed += 1

    # 3. Login User
    total += 1
    print(f"\n[{total}] Testing POST /api/auth/login ...")
    r = requests.post(
        f"{BASE_URL}/api/auth/login",
        headers={"X-Tenant-ID": tenant_id},
        json={
            "username": test_user,
            "password": test_password
        },
        timeout=10
    )
    assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
    login_data = r.json()
    assert login_data.get("access_token"), "Login did not return access_token"
    headers = {
        "Authorization": f"Bearer {token}",
        "X-Tenant-ID": tenant_id
    }
    print(f"    -> PASSED! Login successful, JWT bearer authenticated.")
    passed += 1

    # 4. Upload Single Photo
    total += 1
    print(f"\n[{total}] Testing POST /api/upload/photo ...")
    img_bytes = create_synthetic_image_bytes()
    files = {
        "file": ("test_sample.jpg", img_bytes, "image/jpeg")
    }
    data = {
        "folder_name": "vacation_2026"
    }
    r = requests.post(
        f"{BASE_URL}/api/upload/photo",
        headers=headers,
        files=files,
        data=data,
        timeout=15
    )
    assert r.status_code == 201, f"Expected 201, got {r.status_code}: {r.text}"
    upload_res = r.json()
    data_dict = upload_res.get("data", upload_res)
    image_id = data_dict.get("image_id")
    assert image_id, f"Upload missing image_id: {upload_res}"
    print(f"    -> PASSED! Uploaded Image ID: {image_id}, Dimensions: {data_dict.get('width')}x{data_dict.get('height')}")
    passed += 1

    # 5. Process Image (Run AI Vision & Embeddings)
    total += 1
    print(f"\n[{total}] Testing POST /api/process/image/{image_id} ...")
    r = requests.post(
        f"{BASE_URL}/api/process/image/{image_id}",
        headers=headers,
        timeout=30
    )
    assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
    proc_res = r.json()
    print(f"    -> PASSED! Status: {proc_res.get('status')}, Faces: {proc_res.get('faces_detected')}, Objects: {proc_res.get('objects_detected')}")
    passed += 1

    # 6. Search by Image
    total += 1
    print(f"\n[{total}] Testing POST /api/search/image ...")
    query_files = {
        "file": ("query.jpg", img_bytes, "image/jpeg")
    }
    query_data = {
        "top_k": "5",
        "threshold": "0.1"
    }
    r = requests.post(
        f"{BASE_URL}/api/search/image",
        headers=headers,
        files=query_files,
        data=query_data,
        timeout=30
    )
    assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
    search_res = r.json()
    matches = search_res.get("results") or []
    print(f"    -> PASSED! Returned {len(matches)} matches, Total indexed: {search_res.get('total_results', 0)}")
    passed += 1

    # 7. Telemetry / Client Log
    total += 1
    print(f"\n[{total}] Testing POST /api/log ...")
    r = requests.post(
        f"{BASE_URL}/api/log",
        headers=headers,
        json={"event": "ui_click", "details": {"button": "search"}},
        timeout=10
    )
    assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
    print(f"    -> PASSED! Telemetry event ingested.")
    passed += 1

    print(f"\n=======================================================")
    print(f"   ALL {passed}/{total} ENDPOINT TESTS COMPLETED SUCCESSFULLY!  ")
    print(f"=======================================================")

if __name__ == "__main__":
    try:
        run_all_tests()
    except Exception as e:
        print(f"\n[FAILED] Test error: {e}", file=sys.stderr)
        sys.exit(1)
