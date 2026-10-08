# System Flow & Working

This document details the lifecycle of every core user operation in the **Visual Search API**: Single Photo Ingestion, Batch Upload via Background Job Queue, Face Identity Clustering, Single-Image Search, and Multi-Angle Composite Face Search.

---

## 1. Single Photo Upload & Ingestion Flow

When a user uploads a single image via `POST /api/upload`:

```mermaid
sequenceDiagram
    autonumber
    actor User as Client
    participant Router as upload_routes.py
    participant Svc as PhotoUploadService
    participant Quality as OpenCV Quality Checker
    participant Cloud as Cloudinary CDN
    participant Disk as saved_images/ Cache
    participant KV as SQLite KV Cache

    User->>Router: POST /api/upload (File or Image URL, folder_name)
    Router->>Svc: ingest_single_photo(contents, filename, folder_name)
    Svc->>Quality: Check dimensions (min 64x64) and blur (Laplacian variance)
    alt Image Invalid or Corrupted
        Quality-->>Svc: Validation Error
        Svc-->>Router: HTTP 400 Bad Request
    else Valid Image
        Quality-->>Svc: Valid Resolution & Sharpness
        Svc->>Disk: Persist raw image to saved_images/{folder}/{image_id}_{filename}
        Svc->>Cloud: Upload to Cloudinary folder (public_id: img_{image_id})
        Cloud-->>Svc: Secure HTTPS CDN URL
        Svc->>KV: Save image metadata (dimensions, blur, cloud_url)
        Svc-->>Router: UploadResponse (image_id, cloud_url, status: success)
        Router-->>User: 200 OK
    end
```

---

## 2. Asynchronous Batch Upload & Background Job Queue

For high-volume photo uploads (e.g., zip files or dozens of images), the API decouples network ingestion from model inference using a background job queue:

```mermaid
sequenceDiagram
    autonumber
    actor User as Client
    participant Router as upload_routes.py
    participant Jobs as Job Manager (jobs.py)
    participant Worker as Background Async Worker
    participant Cloud as Cloudinary
    participant AI as AIModelManager
    participant FAISS as FAISSEngine
    participant DB as SQLite Database

    User->>Router: POST /api/upload/batch (Files, folder_name)
    Router->>Jobs: create_job(user_id, folder, total_files, payload)
    Jobs->>DB: INSERT INTO upload_jobs (status='pending', stage='queued')
    Jobs-->>Router: Returns job_id
    Router-->>User: 202 Accepted (job_id, status: queued)

    loop Worker Loop (run_worker)
        Worker->>Jobs: Pop job_id from queue
        Worker->>DB: UPDATE upload_jobs (status='processing', stage='inferencing')
        
        par Simultaneous Upload and AI Inference
            Worker->>Cloud: upload_to_cloudinary (via asyncio.to_thread)
        and
            Worker->>AI: process_image_bytes_async (via semaphore)
        end

        Worker->>FAISS: batch_upsert_all (ArcFace 512D, AdaFace 512D, DINOv2 1536D)
        Worker->>DB: INSERT INTO vector_metadata (image_id, vector_id, url, folder)
        Worker->>DB: UPDATE upload_jobs (processed_files += 1, stage='indexing')
    end

    Worker->>DB: UPDATE upload_jobs (status='completed', stage='completed')
    
    User->>Router: GET /api/jobs/{job_id}
    Router-->>User: JobProgressResponse (status='completed', processed_files, logs)
```

---

## 3. Visual Search Pipeline (Single Query Image)

When a query image is submitted to `POST /api/search/image`:

```mermaid
flowchart TD
    Start["POST /api/search/image<br/>(file or image_url, folder_name, threshold)"] --> Decode["Decode Image into OpenCV BGR Array"]
    Decode --> CheckFolder{"folder_name specified?"}
    
    CheckFolder -- Yes --> ValidateFolder["Verify target folder image count in SQLite<br/>(If 0, return 404)"]
    CheckFolder -- No --> DetectFace["Execute InsightFace SCRFD Face Detector"]
    ValidateFolder --> DetectFace

    DetectFace --> HasFace{"Face detected?"}

    subgraph FaceLane ["Face Search Lane"]
        HasFace -- Yes (>= 1 face) --> ExtractFaces["Extract Dual Embeddings:<br/>1. ArcFace w600k_r50 (512D)<br/>2. AdaFace iResNet-50 (512D)"]
        ExtractFaces --> NormFaces["L2 Normalize Vectors (Unit Length)"]
        NormFaces --> QueryArcFace["FAISS search_vectors on faces-arcface<br/>(Inner Product, Top-K x 2)"]
        NormFaces --> QueryAdaFace["FAISS search_vectors on faces-adaface<br/>(Inner Product, Top-K x 2)"]
        QueryArcFace & QueryAdaFace --> FuseScores["Weighted Score Fusion:<br/>Score = 0.60 * ArcFace + 0.40 * AdaFace"]
        FuseScores --> FilterThreshold["Filter matches where Score >= threshold"]
    end

    subgraph ObjectLane ["Object / Scene Search Lane"]
        HasFace -- No (0 faces) --> ExtractObject["Extract Multimodal Scene Embedding:<br/>DINOv2 ViT-B/14 (768D) + SigLIP (768D)<br/>= 1536D Fused Vector"]
        ExtractObject --> NormObj["L2 Normalize Vector"]
        NormObj --> QueryObjects["FAISS search_vectors on enterprise-objects<br/>(Inner Product, Top-K)"]
        QueryObjects --> FilterObjThreshold["Filter matches where Score >= threshold"]
    end

    FilterThreshold --> Deduplicate["Deduplicate by image_id (keep highest score)"]
    FilterObjThreshold --> Deduplicate
    Deduplicate --> ResolveURL["Resolve Cloudinary CDN URL and Cluster ID for each match"]
    ResolveURL --> FinalResponse["Return SearchResponse<br/>(query_type, total_matches, results)"]
```

---

## 4. Multi-Angle Composite Face Search Pipeline

Real-world security and enterprise gallery applications often encounter severe pose variations (profiles, head tilts). The endpoint `POST /api/search/multi-angle` solves this via **perspective fusion**:

1. **Input Submission**: Accepts up to three perspective images of the same individual:
   - Frontal face (`front_file` or `front_url`)
   - Left profile (`left_file` or `left_url`)
   - Right profile (`right_file` or `right_url`)
2. **Feature Extraction**:
   - For each provided angle, faces are detected and extracted into ArcFace 512D and AdaFace 512D vectors.
3. **Adaptive Angle Weighting**:
   - `fuse_angle_embeddings` combines vectors with optimal perspective weighting:
     $$\mathbf{v}_{\text{composite}} = 0.50 \cdot \mathbf{v}_{\text{front}} + 0.25 \cdot \mathbf{v}_{\text{left}} + 0.25 \cdot \mathbf{v}_{\text{right}}$$
   - If only front and one side angle are provided, weights automatically re-normalize (e.g. 65% front, 35% side).
4. **Vector Normalization**: The resulting composite vector is L2-normalized:
   $$\hat{\mathbf{v}} = \frac{\mathbf{v}_{\text{composite}}}{\|\mathbf{v}_{\text{composite}}\|_2}$$
5. **FAISS Query**: The composite vector searches the gallery, successfully retrieving targets regardless of whether stored gallery photos captured frontal or side angles.

---

## 5. Automated Face Identity Clustering (HDBSCAN)

To create people albums from thousands of unlabeled photos:

1. **Vector Retrieval**: All face vectors indexed in a target folder (or globally) are reconstructed from FAISS `faces-arcface` (512D).
2. **HDBSCAN Clustering**:
   - Density-based clustering groups vectors without requiring the number of identities ($k$) to be predefined.
   - Vectors that do not confidently belong to any dense identity cluster are marked as noise (`-1`) to avoid false identity merges.
3. **Cluster Medoid Selection**:
   - For each discovered identity cluster, the algorithm computes the pairwise cosine distance matrix between all member faces:
     $$\text{medoid} = \arg\min_{i} \sum_{j} (1 - \mathbf{v}_i \cdot \mathbf{v}_j)$$
   - The face closest to the geometric center becomes the representative **medoid photo**.
4. **Persistence**:
   - Clusters are stored in SQLite `face_clusters` with `cluster_id`, `person_name`, `face_count`, and `medoid_cloudinary_url`.
   - Vector mappings are saved in `face_vector_clusters` for immediate lookup by `image_id`.

