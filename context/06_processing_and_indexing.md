# Image Processing & Vector Indexing Pipeline

This document details the step-by-step image processing pipeline, validation rules, FAISS index structures, dual indexing strategies, SQLite metadata synchronization, and Cloudinary asset resolution.

---

## 1. Input Image Ingestion & Quality Validation

Before any model inference or indexing takes place, input images pass strict validation rules in [`src/modules/vision/image_preprocessor.py`](file:///home/sudhanshu/Desktop/visual-search-api/src/modules/vision/image_preprocessor.py):

1. **Format & Decoding**:
   - Decoded using OpenCV `cv2.imdecode` into BGR NumPy arrays.
   - Corrupted or truncated image streams trigger immediate `400 Bad Request` responses.
2. **Dimension Guards**:
   - Minimum resolution: $64 \times 64$ pixels.
   - Maximum resolution: Uncapped, but images larger than 1920px are proportionally resized to preserve aspect ratio while avoiding CPU memory spikes.
3. **Blur Filtering (Laplacian Variance)**:
   - Evaluates the second derivative of the grayscale image:
     $$\sigma^2 = \text{Var}\left( \nabla^2 I_{\text{gray}} \right)$$
   - If $\sigma^2 < \text{FACE\_BLUR\_THRESHOLD}$ (default 20.0), the face candidate is considered too blurry to provide reliable biometric embeddings and is skipped.

---

## 2. FAISS Vector Stores Architecture

The vector engine maintains 4 primary in-memory and on-disk indices in `data/faiss/`:

```
data/faiss/
├── enterprise-faces.index    # 512D ArcFace unified face gallery index
├── faces-arcface.index       # 512D ArcFace primary face index
├── faces-adaface.index       # 512D AdaFace secondary quality-adaptive index
└── enterprise-objects.index  # 1536D DINOv2 (768D) + SigLIP (768D) scene index
```

### Index Specifications & Dimensions

| Index Name | Embedding Model | Vector Dimension | Metric Type | Internal Implementation |
| :--- | :--- | :--- | :--- | :--- |
| `faces-arcface` | ArcFace (w600k_r50) | **512** | Inner Product (`METRIC_INNER_PRODUCT`) | `IndexIDMap2(IndexFlatIP(512))` |
| `faces-adaface` | AdaFace (iResNet-50) | **512** | Inner Product (`METRIC_INNER_PRODUCT`) | `IndexIDMap2(IndexFlatIP(512))` |
| `enterprise-faces`| ArcFace (w600k_r50) | **512** | Inner Product (`METRIC_INNER_PRODUCT`) | `IndexIDMap2(IndexFlatIP(512))` |
| `enterprise-objects`| DINOv2 + SigLIP | **1536** | Inner Product (`METRIC_INNER_PRODUCT`) | `IndexIDMap2(IndexFlatIP(1536))` |

### ID Mapping Strategy
FAISS natively indexes vectors using monotonic 64-bit integers (`int64`). To map string IDs (`face_fe1854012048_0`, `obj_fe1854012048`), the system implements a dual-key architecture:
- **`int_id` (Integer)**: Managed by SQLite `AUTOINCREMENT` primary key in `vector_metadata`.
- **`vector_id` (String)**: Canonical business identifier combining `image_id` and detection index.
- Native `IndexIDMap2` associates the vector directly with `int_id`, allowing $O(1)$ vector retrieval and deletion by ID without re-indexing the entire store.

---

## 3. SQLite Metadata Synchronization

For every vector inserted into FAISS, an atomic database transaction updates SQLite table `vector_metadata`:

```sql
CREATE TABLE IF NOT EXISTS vector_metadata (
    int_id INTEGER PRIMARY KEY AUTOINCREMENT,
    index_name TEXT NOT NULL,
    vector_id TEXT NOT NULL,
    url TEXT,
    folder TEXT,
    metadata_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
```

### Fields Stored in `metadata_json`
```json
{
  "image_id": "fe1854012048",
  "bbox": [541, 141, 84, 107],
  "blur_score": 2001.59,
  "user_id": "user_test",
  "face_idx": 0,
  "folder": "general",
  "url": "https://res.cloudinary.com/ks28qusz/image/upload/v1791451186/general/img_fe1854012048.jpg"
}
```

### Benefits of Metadata Coupling
- **Folder Scoping**: Search queries scoped with `folder_name='general'` filter vectors during the search loop, ensuring zero cross-folder data leakage.
- **Bounding Boxes**: Exact pixel coordinates `[x, y, width, height]` return with every search match so frontend apps can render face highlight boxes immediately.

---

## 4. Cloudinary Asset URL Resolution

Every search match formats and resolves the permanent Cloudinary CDN URL:

1. **Pre-populated URL**: If `vector_metadata.url` contains the Cloudinary HTTPS URL, it is returned directly.
2. **Deterministic Fallback**: If the URL is empty or unpopulated, the resolution layer dynamically formats:
   ```
   https://res.cloudinary.com/{cloud_name}/image/upload/{folder}/img_{image_id}.jpg
   ```
3. **Cluster Medoid URL**: When clusters are formed, the representative medoid photo stores its exact Cloudinary CDN URL in `face_clusters.medoid_cloudinary_url`, enabling instant identity album thumbnails in UI cards.

