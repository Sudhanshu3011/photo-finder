# AI Models & Embedding Management

The **Visual Search API** is powered by an ensemble of state-of-the-art computer vision models coordinated through [`src/services/ai_manager.py`](file:///home/sudhanshu/Desktop/visual-search-api/src/services/ai_manager.py).

---

## Model Inventory & Technical Specifications

| Model | Architecture | Role / Purpose | Embedding Dimension | Framework / Runtime |
| :--- | :--- | :--- | :--- | :--- |
| **SCRFD 10G** (InsightFace) | Deep CNN + Feature Pyramid Network | High-precision face detection & 5-point landmark localization | N/A (Bounding Box + Landmarks) | ONNX Runtime (CPU) |
| **ArcFace w600k_r50** (InsightFace) | ResNet-50 with Additive Angular Margin | Primary face feature extraction | **512D** | ONNX Runtime (CPU) |
| **AdaFace** | iResNet-50 with Adaptive Quality Margin | Secondary face feature extraction (low-light, blurry, extreme angle) | **512D** | PyTorch (TorchScript / CPU) |
| **YOLOv11** | Ultralytics YOLOv11 | Object bounding box proposals & scene localization | Bounding boxes & class IDs | PyTorch / Ultralytics |
| **DINOv2** | Vision Transformer (`vit_base_patch14_reg4_dinov2`) | Self-supervised visual representation & geometry | **768D** | PyTorch (HuggingFace Hub) |
| **SigLIP** | Sigmoid Vision-Language Transformer (`ViT-SO400M-14-SigLIP`) | Semantic & zero-shot visual concepts | **768D** | PyTorch (HuggingFace Hub) |
| **HDBSCAN** | Hierarchical Density-Based Clustering | Identity clustering & medoid representative discovery | Distance Matrix | `scikit-learn` / `hdbscan` |

---

## 1. Face Detection & Alignment (InsightFace SCRFD 10G)

The face detection pipeline uses SCRFD (Sample and Computation Redistribution for Efficient Face Detection):
- **Detection Resolution**: Standardized to `(640, 640)` for optimal CPU throughput.
- **Landmark Alignment**: 5 key facial points (left eye, right eye, nose tip, left mouth corner, right mouth corner).
- **Affine Transformation**: Faces are cropped with an affine similarity transformation aligning the eyes horizontally and centering the nose, outputting a normalized `112x112` face chip required by ArcFace and AdaFace.
- **Quality Filtering**: Laplacian variance filter rejects severely blurred crops:
  $$\text{Blur Score} = \text{Var}(\nabla^2 I)$$
  Faces with variance below `FACE_BLUR_THRESHOLD` are discarded to prevent index contamination.

---

## 2. Dual Face Embedding Extraction: ArcFace & AdaFace

### ArcFace (w600k_r50)
- Extracts a 512-dimensional vector on the unit hypersphere:
  $$\|\mathbf{v}_{\text{arc}}\|_2 = 1.0$$
- Trained on WebFace600K with angular margin loss:
  $$L = -\log \frac{e^{s(\cos(\theta_{y_i} + m))}}{e^{s(\cos(\theta_{y_i} + m))} + \sum_{j \neq y_i} e^{s \cos \theta_j}}$$
- Generates discriminative clusters with large angular distance between different identities.

### AdaFace (iResNet-50)
- Addresses real-world degradation where ArcFace confidence drops.
- AdaFace dynamically modulates angular margin $m$ based on feature norm $\|\mathbf{z}_i\|$, serving as an image quality proxy:
  $$m = -\hat{\|\mathbf{z}_i\|} \cdot m_{\text{margin}}$$
- Blurry or low-resolution crops are penalized less harshly, ensuring valid representation where ArcFace fails.

---

## 3. General Object & Scene Embeddings: DINOv2 + SigLIP

When an input photo contains **no human faces** (e.g. landscapes, products, vehicles, food, animals), the system automatically routes to the **Object Lane**:

1. **DINOv2 (ViT-B/14)**:
   - Self-supervised foundation vision transformer from Meta AI.
   - Excels at dense geometric representation, texture recognition, and part-level correspondence (768D).
2. **SigLIP (ViT-SO400M)**:
   - Google's vision transformer trained with sigmoid loss on image-text pairs.
   - Captures high-level semantic meaning and context (768D).
3. **Multimodal Fusion**:
   - Both 768D vectors are L2-normalized, concatenated into a composite **1536D** vector, and re-normalized:
     $$\mathbf{v}_{\text{fused}} = \left[ \frac{\mathbf{v}_{\text{dino}}}{\|\mathbf{v}_{\text{dino}}\|_2} \;,\; \frac{\mathbf{v}_{\text{siglip}}}{\|\mathbf{v}_{\text{siglip}}\|_2} \right]$$
     $$\hat{\mathbf{v}}_{\text{fused}} = \frac{\mathbf{v}_{\text{fused}}}{\|\mathbf{v}_{\text{fused}}\|_2}$$
   - Indexed into FAISS `enterprise-objects` (1536D).

---

## 4. Role of YOLOv11

**YOLOv11** operates as an auxiliary vision model:
- Detects discrete object bounding boxes (vehicles, animals, furniture, electronics).
- In batch and processing flows, it enables object crop proposals and scene classification.
- Works in tandem with DINOv2/SigLIP to localize and isolate primary foreground subjects from busy backgrounds.

---

## 5. Embedding Management & Cosine Similarity Mathematics

All vectors stored in FAISS are **strictly unit-normalized ($L_2$ norm = 1.0)**:
$$\hat{\mathbf{x}} = \frac{\mathbf{x}}{\sqrt{\sum_{i=1}^d x_i^2}}$$

### Why Inner Product (IP) Equals Cosine Similarity
For any two unit vectors $\hat{\mathbf{a}}$ and $\hat{\mathbf{b}}$:
$$\text{Cosine Similarity}(\hat{\mathbf{a}}, \hat{\mathbf{b}}) = \frac{\hat{\mathbf{a}} \cdot \hat{\mathbf{b}}}{\|\hat{\mathbf{a}}\|_2 \|\hat{\mathbf{b}}\|_2} = \hat{\mathbf{a}} \cdot \hat{\mathbf{b}} = \sum_{i=1}^d \hat{a}_i \hat{b}_i$$

By using `faiss.IndexFlatIP` on unit-normalized vectors:
1. Search measures **exact Cosine Similarity** in $[-1.0, 1.0]$ (clipped to $[0.0, 1.0]$ for matching).
2. CPU SIMD vector instructions (AVX2 / FMA) perform dot products without expensive square-root or division operations during query time.
3. Sub-millisecond similarity search across tens of thousands of vectors.

---

## 6. Score Fusion Formula

When querying the dual face indices:
$$\text{Similarity Score} = w_{\text{arc}} \cdot S_{\text{ArcFace}} + w_{\text{ada}} \cdot S_{\text{AdaFace}}$$
where $w_{\text{arc}} = 0.60$ and $w_{\text{ada}} = 0.40$.

If AdaFace is unavailable or the crop is too degraded:
$$\text{Similarity Score} = S_{\text{ArcFace}}$$
Matches are accepted if $\text{Similarity Score} \ge \text{threshold}$ (configurable per query, default `0.60`, with `0.30`–`0.40` recommended for diverse lighting and pose variations).

