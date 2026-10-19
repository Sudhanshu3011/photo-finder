# Visual Search API — Operations & Endpoints Guide

A comprehensive operational manual covering Docker lifecycle management, container logging, Celery monitoring, and complete endpoint specifications with concrete `curl` examples and payloads.

---

## Table of Contents
1. [Service Architecture & Ports](#1-service-architecture--ports)
2. [Docker Commands & Operations](#2-docker-commands--operations)
   - [Starting Services](#starting-services)
   - [Checking Service Health & Status](#checking-service-health--status)
   - [Reading Container Logs](#reading-container-logs)
   - [Restarting & Stopping Containers](#restarting--stopping-containers)
   - [Debugging & Shell Access](#debugging--shell-access)
3. [Interactive Web Dashboards](#3-interactive-web-dashboards)
4. [API Endpoints Reference](#4-api-endpoints-reference)
   - [System & Health](#a-system--health)
   - [Authentication & Multi-Tenant Management](#b-authentication--multi-tenant-management)
   - [Photo Upload & Ingestion](#c-photo-upload--ingestion)
   - [AI Inference & Face Clustering](#d-ai-inference--face-clustering)
   - [Visual & Multimodal Search](#e-visual--multimodal-search)
5. [Automated Verification](#5-automated-verification)
6. [Troubleshooting & FAQs](#6-troubleshooting--faqs)

---

## 1. Service Architecture & Ports

The application consists of modular, containerized services managed through `docker-compose.yml`:

| Container Name | Service Role | Host Port | Internal Port | Description |
| :--- | :--- | :--- | :--- | :--- |
| `visual_search_api` | FastAPI Core API | `7860` | `7860` | High-performance async REST API engine |
| `visual_search_postgres` | PostgreSQL Database | `5433` | `5432` | Relational store with Row-Level Security (RLS) |
| `visual_search_redis` | Redis Broker / Cache | `6379` | `6379` | Celery message broker, task queue & state store |
| `visual_search_worker_ingest` | Celery Worker (Ingest) | — | — | Consumes `queue.ingest` (validates, deduplicates, uploads) |
| `visual_search_worker_inference` | Celery Worker (Inference) | — | — | Consumes `queue.inference` (extracts AI embeddings) |
| `visual_search_worker_clustering` | Celery Worker (Clustering) | — | — | Consumes `queue.clustering` (runs HDBSCAN face grouping) |
| `visual_search_flower` | Celery Dashboard (Flower) | `5555` | `5555` | Real-time task tracking & worker metrics UI |
| `visual_search_triton` | NVIDIA Triton Server | `8000, 8001, 8002` | `8000, 8001, 8002` | Optional GPU accelerated inference engine |

> [!NOTE]
> **PostgreSQL Port 5433**: The host mapping uses `5433:5432` to avoid collisions if your host machine already runs a local PostgreSQL service on `5432`. Inside the Docker network, all services communicate seamlessly over `postgres:5432`.

---

## 2. Docker Commands & Operations

### Starting Services

#### Start All Services (Recommended)
```bash
docker compose up -d
```

#### Start Core Dependencies Only (Postgres + Redis)
```bash
docker compose up -d postgres redis
```

#### Start API Service
```bash
docker compose up -d api
```

#### Start Celery Worker Fleet & Flower Dashboard
```bash
docker compose up -d worker-ingest worker-inference worker-clustering flower
```

---

### Checking Service Health & Status

#### View Live Running Containers
```bash
docker compose ps
# or
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
```

#### Test Redis Health
```bash
docker exec visual_search_redis redis-cli ping
# Expected output: PONG
```

#### Test PostgreSQL Health
```bash
docker exec visual_search_postgres pg_isready -U postgres -d visual_search
# Expected output: /var/run/postgresql:5432 - accepting connections
```

#### Ping Active Celery Workers
```bash
docker exec visual_search_api celery -A celery_app.app inspect ping
# Expected output:
# -> celery@...: OK
#     pong
```

---

### Reading Container Logs

#### Stream Real-Time Logs (Follow Mode)
```bash
# API logs
docker logs -f visual_search_api

# Celery Ingestion Worker logs
docker logs -f visual_search_worker_ingest

# Celery Inference Worker logs
docker logs -f visual_search_worker_inference

# Celery Clustering Worker logs
docker logs -f visual_search_worker_clustering

# Flower Dashboard logs
docker logs -f visual_search_flower

# PostgreSQL logs
docker logs -f visual_search_postgres

# Redis logs
docker logs -f visual_search_redis
```

#### View Recent N Lines (Without Following)
```bash
docker logs --tail 50 visual_search_api
docker logs --tail 100 visual_search_worker_ingest
```

#### View Logs Across All Services Simultaneously
```bash
docker compose logs -f --tail 20
```

---

### Restarting & Stopping Containers

#### Restart a Specific Container
```bash
docker compose restart api
docker compose restart worker-ingest
docker compose restart worker-inference
docker compose restart flower
```

#### Stop All Services Gracefully (Data Preserved)
```bash
docker compose stop
```

#### Tear Down Containers & Networks (Data Volumes Preserved)
```bash
docker compose down
```

#### Tear Down and Delete Persistent Volumes (Wipe All DB & Indices)
```bash
docker compose down -v
```

---

### Debugging & Shell Access

#### Enter API Container Bash Shell
```bash
docker exec -it visual_search_api bash
```

#### Connect to PostgreSQL Interactive CLI (`psql`)
```bash
docker exec -it visual_search_postgres psql -U postgres -d visual_search
```
*Useful SQL queries once inside:*
```sql
\dt                          -- List all tables
SELECT * FROM tenants;       -- View registered tenants
SELECT * FROM users;         -- View registered users
SELECT count(*) FROM images; -- Count indexed images
\q                           -- Exit psql
```

#### Connect to Redis CLI
```bash
docker exec -it visual_search_redis redis-cli
```
*Useful Redis commands:*
```text
KEYS *                       -- List cached keys
INFO stats                   -- Inspect hit rates & memory
FLUSHDB                      -- Clear cache (Caution!)
```

---

## 3. Interactive Web Dashboards

Once services are running, open your browser to access the interactive web portals:

1. **FastAPI Interactive API Documentation (Swagger UI)**:
   👉 [http://localhost:7860/docs](http://localhost:7860/docs)
   - Execute requests directly in the browser
   - Authenticate with JWT Bearer tokens
   - Test photo uploads and vector queries

2. **Celery Flower Monitoring Portal**:
   👉 [http://localhost:5555](http://localhost:5555)
   - Real-time task throughput & latency charts
   - Worker concurrency & load averages
   - Ingest, inference, and clustering queue lengths

---

## 4. API Endpoints Reference

All endpoints accept and enforce multi-tenant isolation via standard headers:
- `Authorization: Bearer <access_token>`
- `X-Tenant-ID: <tenant_id>` *(Optional: defaults to user's registered tenant)*

---

### A. System & Health

#### 1. System Health Check
Check application status and operational readiness.

* **Endpoint**: `GET /api/health`
* **Auth**: Public
* **cURL**:
  ```bash
  curl -s http://localhost:7860/api/health
  ```
* **Success Response (200 OK)**:
  ```json
  {
    "status": "ok",
    "app": "Visual Search API",
    "version": "2.0.0",
    "timestamp": "2026-10-15T10:50:00.000000+00:00"
  }
  ```

#### 2. Client Telemetry Ingestion
Ingests frontend errors and button-click analytics.

* **Endpoint**: `POST /api/log`
* **Auth**: Public / Authenticated
* **cURL**:
  ```bash
  curl -s -X POST http://localhost:7860/api/log \
    -H "Content-Type: application/json" \
    -d '{"event": "search_button_clicked", "page": "/gallery"}'
  ```
* **Success Response (200 OK)**:
  ```json
  {
    "success": true,
    "message": "Event logged successfully"
  }
  ```

---

### B. Authentication & Multi-Tenant Management

#### 1. Register User & Tenant
Creates a new tenant-isolated account and returns a JWT access token.

* **Endpoint**: `POST /api/auth/register`
* **Auth**: Public
* **cURL**:
  ```bash
  curl -s -X POST http://localhost:7860/api/auth/register \
    -H "Content-Type: application/json" \
    -d '{
      "username": "alex",
      "email": "alex@example.com",
      "password": "Password123!",
      "tenant_id": "tenant_studio_a",
      "role": "user"
    }'
  ```
* **Success Response (201 Created)**:
  ```json
  {
    "access_token": "eyJhbGciOiJIUzI1NiIsIn...",
    "token_type": "bearer",
    "user_id": "user_a1b2c3d4e5f6",
    "username": "alex",
    "role": "user",
    "tenant_id": "tenant_studio_a"
  }
  ```

#### 2. User Login
Authenticate credentials to obtain a fresh access token.

* **Endpoint**: `POST /api/auth/login`
* **Auth**: Public
* **Headers**: `X-Tenant-ID: <tenant_id>` *(Optional)*
* **cURL**:
  ```bash
  curl -s -X POST http://localhost:7860/api/auth/login \
    -H "Content-Type: application/json" \
    -d '{
      "username": "alex",
      "password": "Password123!"
    }'
  ```
* **Success Response (200 OK)**:
  ```json
  {
    "access_token": "eyJhbGciOiJIUzI1NiIsIn...",
    "token_type": "bearer",
    "user_id": "user_a1b2c3d4e5f6",
    "username": "alex",
    "role": "user",
    "tenant_id": "tenant_studio_a"
  }
  ```

#### 3. View Current User Profile
* **Endpoint**: `GET /api/auth/me`
* **Auth**: Bearer Token
* **cURL**:
  ```bash
  curl -s http://localhost:7860/api/auth/me \
    -H "Authorization: Bearer <TOKEN>"
  ```

---

### C. Photo Upload & Ingestion

#### 1. Upload Single Photo
Uploads an image file or provides a remote image URL for validation, local persistence, and S3 upload.

* **Endpoint**: `POST /api/upload/photo`
* **Auth**: Bearer Token
* **Content-Type**: `multipart/form-data`
* **Parameters (Form Data)**:
  - `file`: Image binary (`image/jpeg`, `image/png`, `image/webp` — **Maximum size: 20MB per image**)
  - `folder_name`: Target album/collection (e.g. `wedding_2026`, `family`)
  - `image_url`: *(Optional)* Direct remote image URL if not uploading a local file
* **Validation & Limits**:
  - Max file size: **20 MB** per image. Uploads exceeding 20MB receive `413 Request Entity Too Large`.
  - Max batch size: **50** files per batch request.
* **cURL (File Upload)**:
  ```bash
  curl -s -X POST http://localhost:7860/api/upload/photo \
    -H "Authorization: Bearer <TOKEN>" \
    -H "X-Tenant-ID: tenant_studio_a" \
    -F "file=@/path/to/my_photo.jpg" \
    -F "folder_name=wedding_2026"
  ```
* **Success Response (201 Created)**:
  ```json
  {
    "status": "success",
    "data": {
      "image_id": "img_7f8a9b0c1d2e",
      "filename": "my_photo.jpg",
      "folder": "wedding_2026",
      "status": "success",
      "message": "Photo uploaded and stored successfully",
      "width": 1920,
      "height": 1080,
      "is_blurry": false,
      "cloud_url": "https://my-visual-search-media-v1.s3.amazonaws.com/tenant_studio_a/wedding_2026/img_7f8a9b0c1d2e.jpg"
    }
  }
  ```

#### 2. Batch Photo Upload
Upload multiple photos concurrently in a single multipart request.

* **Endpoint**: `POST /api/upload/batch`
* **Auth**: Bearer Token
* **cURL**:
  ```bash
  curl -s -X POST http://localhost:7860/api/upload/batch \
    -H "Authorization: Bearer <TOKEN>" \
    -F "files=@photo1.jpg" \
    -F "files=@photo2.jpg" \
    -F "folder_name=trip_2026"
  ```

---

### D. AI Inference & Face Clustering

#### 1. Process Uploaded Image (Feature Extraction)
Extracts SCRFD face landmarks, ArcFace / AdaFace embeddings (512D), and SigLIP + DINOv2 scene embeddings (1536D), automatically adding them to the tenant's FAISS vector indices.

* **Endpoint**: `POST /api/process/image/{image_id}`
* **Auth**: Bearer Token
* **cURL**:
  ```bash
  curl -s -X POST http://localhost:7860/api/process/image/img_7f8a9b0c1d2e \
    -H "Authorization: Bearer <TOKEN>"
  ```
* **Success Response (200 OK)**:
  ```json
  {
    "image_id": "img_7f8a9b0c1d2e",
    "faces_detected": 2,
    "objects_detected": 1,
    "status": "success",
    "message": "Processed 2 face(s) and scene vectors into FAISS"
  }
  ```

#### 2. Generate Identity Clusters (HDBSCAN Albums)
Clusters extracted face embeddings in an album to discover unique identities/people.

* **Endpoint**: `POST /api/clusters/generate`
* **Auth**: Bearer Token
* **Query Parameters**:
  - `folder_name` (string, required): Target folder/album name
  - `min_cluster_size` (int, default: 3): Minimum face appearances to form a person cluster
  - `epsilon` (float, default: 0.25): Distance tolerance
* **cURL**:
  ```bash
  curl -s -X POST "http://localhost:7860/api/clusters/generate?folder_name=wedding_2026&min_cluster_size=3" \
    -H "Authorization: Bearer <TOKEN>"
  ```
* **Success Response (200 OK)**:
  ```json
  {
    "status": "success",
    "folder_name": "wedding_2026",
    "clusters_found": 5,
    "total_faces_clustered": 42,
    "message": "Clustering complete"
  }
  ```

#### 3. View Discovered Face Clusters
* **Endpoint**: `GET /api/clusters/all`
* **Auth**: Bearer Token
* **cURL**:
  ```bash
  curl -s "http://localhost:7860/api/clusters/all?folder_name=wedding_2026" \
    -H "Authorization: Bearer <TOKEN>"
  ```

---

### E. Visual & Multimodal Search

#### 1. Search by Image (Visual Similarity & Face Search)
Searches the gallery using a query image. The system automatically detects whether the query contains human faces or scene objects, applying fused cosine similarity scoring.

* **Endpoint**: `POST /api/search/image`
* **Auth**: Bearer Token
* **Parameters (Form Data / Query)**:
  - `file`: Query image file
  - `folder_name`: *(Optional)* Scope search to a specific album
  - `top_k`: Maximum number of results to return (default: 20)
  - `threshold`: Minimum similarity threshold between 0.0 and 1.0 (default: 0.60)
* **cURL**:
  ```bash
  curl -s -X POST http://localhost:7860/api/search/image \
    -H "Authorization: Bearer <TOKEN>" \
    -F "file=@/path/to/search_query.jpg" \
    -F "top_k=10" \
    -F "threshold=0.55"
  ```
* **Success Response (200 OK)**:
  ```json
  {
    "status": "success",
    "total_results": 3,
    "query_type": "face",
    "results": [
      {
        "image_id": "img_7f8a9b0c1d2e",
        "url": "https://my-visual-search-media-v1.s3.amazonaws.com/tenant_studio_a/wedding_2026/img_7f8a9b0c1d2e.jpg",
        "similarity_score": 0.942,
        "folder": "wedding_2026"
      },
      {
        "image_id": "img_9a8b7c6d5e4f",
        "url": "https://my-visual-search-media-v1.s3.amazonaws.com/tenant_studio_a/wedding_2026/img_9a8b7c6d5e4f.jpg",
        "similarity_score": 0.887,
        "folder": "wedding_2026"
      }
    ]
  }
  ```

#### 2. List Indexed Albums
* **Endpoint**: `GET /api/search/folders`
* **Auth**: Bearer Token
* **cURL**:
  ```bash
  curl -s http://localhost:7860/api/search/folders \
    -H "Authorization: Bearer <TOKEN>"
  ```

---

## 5. Automated Verification

We have provided a turnkey Python verification script that exercises all 7 primary lifecycle endpoints in sequence:

```bash
# Execute within the running API container:
docker exec -i visual_search_api python3 < scripts/test_live_endpoints.py
```

### Expected Output:
```text
=== Starting Visual Search API Live Endpoint Verification ===
Target Base URL: http://localhost:7860

[1] Testing GET /api/health ...
    -> PASSED! Status: ok, Version: 2.0.0

[2] Testing POST /api/auth/register (Tenant: tenant_179..., User: tester_179...) ...
    -> PASSED! User ID: user_..., Tenant: tenant_...

[3] Testing POST /api/auth/login ...
    -> PASSED! Login successful, JWT bearer authenticated.

[4] Testing POST /api/upload/photo ...
    -> PASSED! Uploaded Image ID: img_..., Dimensions: 300x300

[5] Testing POST /api/process/image/img_... ...
    -> PASSED! Status: success, Faces: 0, Objects: 1

[6] Testing POST /api/search/image ...
    -> PASSED! Returned 1 matches, Total indexed: 1

[7] Testing POST /api/log ...
    -> PASSED! Telemetry event ingested.

=======================================================
   ALL 7/7 ENDPOINT TESTS COMPLETED SUCCESSFULLY!  
=======================================================
```

---

## 6. Troubleshooting & FAQs

### Q1: `curl: (7) Failed to connect to localhost port 7860: Connection refused`
* **Cause**: The API container is starting up or still downloading/initializing vision models into memory (can take 30–60 seconds on CPU).
* **Fix**: Check logs with `docker logs --tail 20 visual_search_api`. Wait until `Application startup complete` appears.

### Q2: `Task error: cannot perform operation: another operation is in progress`
* **Cause**: Asyncpg connection pool was called across different event loops in a multi-threaded worker.
* **Fix**: This has been resolved in `src/modules/infra/postgres_repository.py` using a persistent thread-safe background event loop (`_run_sync`).

### Q3: What happens if AWS credentials or S3 bucket are missing?
* **Behavior**: The upload will **not** fail. The file is saved to the local host directory `saved_images/`, a canonical S3 key is assigned, and downstream processing continues smoothly.

### Q4: How do I switch to NVIDIA Triton GPU acceleration?
1. Start the Triton container: `docker compose up -d triton-server`
2. Update `.env`:
   ```dotenv
   INFERENCE_BACKEND=triton
   TRITON_SERVER_URL=triton-server:8001
   ```
3. Restart API & Workers:
   ```bash
   docker compose restart api worker-inference
   ```

