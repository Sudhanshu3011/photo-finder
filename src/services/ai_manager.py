import asyncio
import base64
import concurrent.futures
import functools
import io
import os
import threading
import hashlib
import warnings

# InsightFace uses np.linalg.lstsq without rcond — suppress the FutureWarning.
warnings.filterwarnings("ignore", category=FutureWarning, module="insightface")
# Suppress PyTorch meta-tensor copy warnings from AdaFace model loading.
warnings.filterwarnings("ignore", category=UserWarning, module="torch.nn.modules.module")

import cv2
import numpy as np
import torch
import torch.nn.functional as F
from PIL import Image, ImageOps
from transformers import AutoImageProcessor, AutoModel, AutoProcessor
from ultralytics import YOLO
import insightface  # noqa: F401
from insightface.app import FaceAnalysis

from src.core.config import (
    MAX_IMAGE_SIZE, MAX_CROPS, YOLO_PERSON_CLASS_ID,
    YOLO_MIN_CROP_PX, YOLO_CONF_THRESHOLD,
    DET_SIZE_PRIMARY, IOU_DEDUP_THRESHOLD,
    MIN_FACE_SIZE, MAX_FACES_PER_IMAGE, FACE_QUALITY_GATE,
    FACE_DIM, ADAFACE_DIM,
    FACE_CROP_THUMB_SIZE, FACE_CROP_QUALITY,
    FACE_CROP_PADDING, ADAFACE_CROP_PADDING,
    INFERENCE_CACHE_SIZE, ENABLE_ADAFACE, HF_TOKEN,
    USE_ONNX_VISION, ONNX_MODELS_DIR, ONNX_USE_INT8,
    ENABLE_MULTI_SCALE_FALLBACK, ENABLE_HORIZONTAL_FLIP,
    USE_SPLIT_FACE_INDEXES, FACE_BLUR_THRESHOLD,
)

# ── ArcFace 5-point reference landmarks (fixed template) ──────────────────────
# Precomputed — eliminates np.linalg.lstsq call per face (10x faster alignment)
_ARCFACE_SRC = np.array([
    [38.2946, 51.6963],
    [73.5318, 51.5014],
    [56.0252, 71.7366],
    [41.5493, 92.3655],
    [70.7299, 92.2041],
], dtype=np.float32)


def _estimate_norm_fast(lmk: np.ndarray, image_size: int = 112) -> np.ndarray:
    """
    Fast affine estimation using cv2.estimateAffinePartial2D instead of
    np.linalg.lstsq. ~10x faster on CPU. Returns 2x3 affine matrix.
    """
    assert lmk.shape == (5, 2), f"Expected (5,2) landmarks, got {lmk.shape}"
    src = _ARCFACE_SRC * (image_size / 112.0)
    tform, _ = cv2.estimateAffinePartial2D(
        lmk, src, method=cv2.LSQR_EXACT, ransacReprojThreshold=100
    )
    if tform is None:
        # Fallback: identity crop — better than crashing
        tform = np.array([[1, 0, 0], [0, 1, 0]], dtype=np.float32)
    return tform


def _align_face_fast(bgr: np.ndarray, kps: np.ndarray, size: int = 112) -> np.ndarray:
    """Align face crop using fast affine transform (replaces InsightFace's lstsq path)."""
    M = _estimate_norm_fast(kps, size)
    aligned = cv2.warpAffine(bgr, M, (size, size), flags=cv2.INTER_LINEAR)
    return aligned


def _resize_pil(img: Image.Image, max_side: int = MAX_IMAGE_SIZE) -> Image.Image:
    w, h = img.size
    if max(w, h) <= max_side:
        return img
    scale = max_side / max(w, h)
    return img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)


def _blur_score(bgr: np.ndarray, x1: int, y1: int, x2: int, y2: int) -> float:
    """Laplacian variance sharpness metric on a face crop. Higher = sharper."""
    crop = bgr[y1:y2, x1:x2]
    if crop.size == 0:
        return 0.0
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    gray = cv2.resize(gray, (64, 64))
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def _crop_to_b64(img_bgr: np.ndarray, x1: int, y1: int, x2: int, y2: int) -> str:
    H, W = img_bgr.shape[:2]
    w, h = x2 - x1, y2 - y1
    pad_x = int(w * FACE_CROP_PADDING)
    pad_y = int(h * FACE_CROP_PADDING)
    cx1, cy1 = max(0, x1 - pad_x), max(0, y1 - pad_y)
    cx2, cy2 = min(W, x2 + pad_x), min(H, y2 + pad_y)
    crop = img_bgr[cy1:cy2, cx1:cx2]
    if crop.size == 0:
        return ""
    pil = Image.fromarray(crop[:, :, ::-1]).resize(
        (FACE_CROP_THUMB_SIZE, FACE_CROP_THUMB_SIZE), Image.LANCZOS
    )
    buf = io.BytesIO()
    pil.save(buf, format="JPEG", quality=FACE_CROP_QUALITY)
    return base64.b64encode(buf.getvalue()).decode()


def _face_crop_for_adaface(
    img_bgr: np.ndarray, x1: int, y1: int, x2: int, y2: int
) -> np.ndarray | None:
    H, W = img_bgr.shape[:2]
    w, h = x2 - x1, y2 - y1
    pad_x = int(w * ADAFACE_CROP_PADDING)
    pad_y = int(h * ADAFACE_CROP_PADDING)
    cx1, cy1 = max(0, x1 - pad_x), max(0, y1 - pad_y)
    cx2, cy2 = min(W, x2 + pad_x), min(H, y2 + pad_y)
    crop = img_bgr[cy1:cy2, cx1:cx2]
    if crop.size == 0:
        return None
    rgb = crop[:, :, ::-1].copy()
    pil = Image.fromarray(rgb).resize((112, 112), Image.LANCZOS)
    arr = np.array(pil, dtype=np.float32) / 255.0
    arr = (arr - 0.5) / 0.5
    return arr.transpose(2, 0, 1)


def _clahe_enhance(bgr: np.ndarray) -> np.ndarray:
    lab = cv2.cvtColor(bgr, cv2.COLOR_BGR2LAB)
    l_ch, a_ch, b_ch = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    l_eq = clahe.apply(l_ch)
    return cv2.cvtColor(cv2.merge([l_eq, a_ch, b_ch]), cv2.COLOR_LAB2BGR)


def _iou(box_a: list, box_b: list) -> float:
    xa, ya = max(box_a[0], box_b[0]), max(box_a[1], box_b[1])
    xb, yb = min(box_a[2], box_b[2]), min(box_a[3], box_b[3])
    inter = max(0, xb - xa) * max(0, yb - ya)
    if inter == 0:
        return 0.0
    area_a = (box_a[2] - box_a[0]) * (box_a[3] - box_a[1])
    area_b = (box_b[2] - box_b[0]) * (box_b[3] - box_b[1])
    return inter / (area_a + area_b - inter)


def _dedup_faces(faces_list: list, iou_thresh: float = IOU_DEDUP_THRESHOLD) -> list:
    if not faces_list:
        return []
    faces_list = sorted(faces_list, key=lambda f: float(f.det_score), reverse=True)
    kept = []
    for face in faces_list:
        b = face.bbox.astype(int)
        box = [b[0], b[1], b[2], b[3]]
        if not any(
            _iou(box, [k.bbox.astype(int)[i] for i in range(4)]) > iou_thresh
            for k in kept
        ):
            kept.append(face)
    return kept


# ── Face crop embedding cache (LRU by crop hash) ──────────────────────────────
# Avoids recomputing ArcFace embeddings for the same face across multiple images
# (e.g. same person appears in 20 photos — only 1 inference call needed)
_FACE_EMBED_CACHE: dict[str, np.ndarray] = {}
_FACE_EMBED_CACHE_MAX = 512
_FACE_EMBED_CACHE_LOCK = threading.Lock()


def _face_cache_get(key: str) -> np.ndarray | None:
    with _FACE_EMBED_CACHE_LOCK:
        return _FACE_EMBED_CACHE.get(key)


def _face_cache_set(key: str, vec: np.ndarray) -> None:
    with _FACE_EMBED_CACHE_LOCK:
        if len(_FACE_EMBED_CACHE) >= _FACE_EMBED_CACHE_MAX:
            # Evict oldest entry
            oldest = next(iter(_FACE_EMBED_CACHE))
            del _FACE_EMBED_CACHE[oldest]
        _FACE_EMBED_CACHE[key] = vec


def _crop_hash(crop_bgr: np.ndarray) -> str:
    """Fast hash of face crop pixels for cache lookup."""
    return hashlib.md5(crop_bgr.tobytes()).hexdigest()


class AIModelManager:
    def __init__(self):
        self.device = "cuda" if torch.cuda.is_available() else "cpu"

        # Vision stack
        self.onnx_vision = None
        if USE_ONNX_VISION:
            try:
                from src.services.onnx_models import ONNXVisionStack
                self.onnx_vision = ONNXVisionStack(
                    ONNX_MODELS_DIR, use_int8=bool(ONNX_USE_INT8)
                )
                print(f"[AIModelManager] ONNX vision loaded (INT8={ONNX_USE_INT8})")
            except Exception as e:
                print(f"[AIModelManager] ONNX failed ({e}), using PyTorch fallback")
                self.onnx_vision = None

        if self.onnx_vision is None:
            self.siglip_processor = AutoProcessor.from_pretrained(
                "google/siglip-base-patch16-224", use_fast=True
            )
            self.siglip_model = AutoModel.from_pretrained(
                "google/siglip-base-patch16-224"
            ).to(self.device).eval()
            self.dinov2_processor = AutoImageProcessor.from_pretrained(
                "facebook/dinov2-base", use_fast=True
            )
            self.dinov2_model = AutoModel.from_pretrained(
                "facebook/dinov2-base"
            ).to(self.device).eval()
            if self.device == "cuda":
                self.siglip_model = self.siglip_model.half()
                self.dinov2_model = self.dinov2_model.half()

        # YOLO
        self.yolo = YOLO("yolo11n-seg.pt")

        # Face detection + ArcFace
        self.face_app = FaceAnalysis(
            name="buffalo_l",
            providers=["CUDAExecutionProvider", "CPUExecutionProvider"]
            if self.device == "cuda" else ["CPUExecutionProvider"],
        )
        self.face_app.prepare(
            ctx_id=0 if self.device == "cuda" else -1, det_size=DET_SIZE_PRIMARY
        )
        self.face_app.get(np.zeros((112, 112, 3), dtype=np.uint8))

        # AdaFace
        self.adaface_model = None
        self._load_adaface()

        self._face_lock = threading.Lock()
        self._cache_lock = threading.Lock()
        self._cache: dict[str, list] = {}

        # Thread pool for parallel ArcFace + AdaFace inference
        # 2 workers = one per model, matches 2 vCPU on HF free tier
        self._embed_pool = concurrent.futures.ThreadPoolExecutor(
            max_workers=2, thread_name_prefix="embed"
        )

    def _load_adaface(self) -> None:
        if not ENABLE_ADAFACE:
            return
        import sys
        REPO_ID = "minchul/cvlface_adaface_ir50_ms1mv2"
        CACHE_PATH = os.path.expanduser(
            "~/.cvlface_cache/minchul/cvlface_adaface_ir50_ms1mv2"
        )
        try:
            from huggingface_hub import hf_hub_download
            from transformers import AutoModel as _HFAutoModel
            os.makedirs(CACHE_PATH, exist_ok=True)
            hf_hub_download(
                repo_id=REPO_ID, filename="files.txt", token=HF_TOKEN,
                local_dir=CACHE_PATH, local_dir_use_symlinks=False,
            )
            with open(os.path.join(CACHE_PATH, "files.txt")) as f:
                extra = [x.strip() for x in f.read().split("\n") if x.strip()]
            for fname in extra + ["config.json", "wrapper.py", "model.safetensors"]:
                if not os.path.exists(os.path.join(CACHE_PATH, fname)):
                    hf_hub_download(
                        repo_id=REPO_ID, filename=fname, token=HF_TOKEN,
                        local_dir=CACHE_PATH, local_dir_use_symlinks=False,
                    )
            cwd = os.getcwd()
            os.chdir(CACHE_PATH)
            sys.path.insert(0, CACHE_PATH)
            try:
                model = _HFAutoModel.from_pretrained(
                    CACHE_PATH, trust_remote_code=True, token=HF_TOKEN,
                    low_cpu_mem_usage=False,
                )
            finally:
                os.chdir(cwd)
                if CACHE_PATH in sys.path:
                    sys.path.remove(CACHE_PATH)
            self.adaface_model = model.to(self.device).eval()
        except Exception as _ada_err:
            import traceback as _tb
            print(f"[CRITICAL] AdaFace failed to load — system will run at degraded recall: {_ada_err}")
            _tb.print_exc()
            self.adaface_model = None

    # ── FIX 1: AdaFace batch embed (unchanged — already correct) ──────────────
    def _adaface_embed_batch(
        self, face_arrs_chw: list[np.ndarray | None]
    ) -> list[np.ndarray | None]:
        if self.adaface_model is None:
            return [None] * len(face_arrs_chw)
        valid_idx = [i for i, a in enumerate(face_arrs_chw) if a is not None]
        if not valid_idx:
            return [None] * len(face_arrs_chw)
        batch = np.stack([face_arrs_chw[i] for i in valid_idx], axis=0)
        batch = np.ascontiguousarray(batch)
        try:
            t = torch.from_numpy(batch).contiguous().to(self.device)
            if self.device == "cuda":
                t = t.half()
            with torch.no_grad():
                out = self.adaface_model(t)
            emb = out if isinstance(out, torch.Tensor) else out.embedding
            emb = F.normalize(emb.float(), p=2, dim=1).cpu().numpy()
        except Exception as e:
            import traceback
            print(f"[AdaFace ERROR] {e}")
            traceback.print_exc()
            return [None] * len(face_arrs_chw)
        result = [None] * len(face_arrs_chw)
        for out_i, in_i in enumerate(valid_idx):
            result[in_i] = emb[out_i]
        return result

    # ── FIX 2: ArcFace batch embed using fast alignment ───────────────────────
    def _arcface_embed_batch(
        self, faces: list, bgr: np.ndarray
    ) -> list[np.ndarray]:
        """
        Extracts ArcFace embeddings for all faces at once.

        Two optimisations over the original per-face path:
        1. Uses cv2.estimateAffinePartial2D instead of np.linalg.lstsq
           for face alignment (~10x faster per face on CPU).
        2. Checks the face-crop LRU cache before running inference — same
           person in 20 photos = 1 inference call.

        Falls back to face.embedding (already computed by InsightFace's
        get() call) if landmark data is unavailable.
        """
        results = []

        for face in faces:
            bbox = face.bbox.astype(int)
            x1, y1, x2, y2 = bbox
            x1, y1 = max(0, x1), max(0, y1)
            x2, y2 = min(bgr.shape[1], x2), min(bgr.shape[0], y2)
            raw_crop = bgr[y1:y2, x1:x2]
            ch = _crop_hash(raw_crop) if raw_crop.size > 0 else ""

            if ch:
                cached_vec = _face_cache_get(ch)
                if cached_vec is not None:
                    results.append(cached_vec)
                    continue

            vec = face.embedding.astype(np.float32) if face.embedding is not None \
                else np.zeros(FACE_DIM, dtype=np.float32)
            n = np.linalg.norm(vec)
            vec = vec / n if n > 0 else vec
            if ch:
                _face_cache_set(ch, vec)
            results.append(vec)

        return results

    def _embed_crops_batch(self, crops: list[Image.Image]) -> list[np.ndarray]:
        if not crops:
            return []
        if self.onnx_vision is not None:
            return self.onnx_vision.encode(crops)
        with torch.no_grad():
            sig_in = self.siglip_processor(images=crops, return_tensors="pt", padding=True)
            sig_in = {k: v.to(self.device) for k, v in sig_in.items()}
            if self.device == "cuda":
                sig_in = {k: v.half() if v.dtype == torch.float32 else v for k, v in sig_in.items()}
            sig_out = self.siglip_model.get_image_features(**sig_in)
            if hasattr(sig_out, "image_embeds"):
                sig_out = sig_out.image_embeds
            elif hasattr(sig_out, "pooler_output"):
                sig_out = sig_out.pooler_output
            elif hasattr(sig_out, "last_hidden_state"):
                sig_out = sig_out.last_hidden_state[:, 0, :]
            elif isinstance(sig_out, tuple):
                sig_out = sig_out[0]
            sig_vecs = F.normalize(sig_out.float(), p=2, dim=1).cpu()

            dino_in = self.dinov2_processor(images=crops, return_tensors="pt")
            dino_in = {k: v.to(self.device) for k, v in dino_in.items()}
            if self.device == "cuda":
                dino_in = {k: v.half() if v.dtype == torch.float32 else v for k, v in dino_in.items()}
            dino_out = self.dinov2_model(**dino_in)
            dino_vecs = F.normalize(dino_out.last_hidden_state[:, 0, :].float(), p=2, dim=1).cpu()
            fused = F.normalize(torch.cat([sig_vecs, dino_vecs], dim=1), p=2, dim=1)
        return [fused[i].numpy() for i in range(len(crops))]

    def _run_detection_at_scale(
        self, bgr_enhanced: np.ndarray, scale: tuple
    ) -> list:
        H, W = bgr_enhanced.shape[:2]
        # Preserve aspect ratio when downscaling. The previous code clamped each
        # dim independently which squashed wide images (e.g. 4032x1816 → 640x640)
        # and produced distorted face crops whose embeddings would not match the
        # same person shot in a normal aspect ratio.
        #
        # NOTE: We keep `input_size` set to the original square `scale`. InsightFace
        # SCRFD internally letterboxes the image into the input_size canvas while
        # preserving aspect ratio — so feeding a (640, 360) image with input_size
        # (640, 640) results in a properly padded 640x640 detector input. The
        # square input_size also matches the ONNX model's expected shape.
        target_max = max(scale[0], scale[1])
        long_side = max(W, H)
        if long_side <= target_max:
            bgr_scaled = bgr_enhanced
            scale_w, scale_h = W, H
        else:
            ratio = target_max / long_side
            scale_w = max(1, int(round(W * ratio)))
            scale_h = max(1, int(round(H * ratio)))
            bgr_scaled = cv2.resize(bgr_enhanced, (scale_w, scale_h))
        try:
            with self._face_lock:
                # input_size must be set inside the lock — setting it outside
                # is a race condition when two inference threads run concurrently,
                # causing the wrong scale to be used and faces to be missed.
                self.face_app.det_model.input_size = scale
                faces_at_scale = self.face_app.get(bgr_scaled)
            sx, sy = W / scale_w, H / scale_h
            for f in faces_at_scale:
                if sx != 1.0 or sy != 1.0:
                    f.bbox[0] *= sx; f.bbox[1] *= sy
                    f.bbox[2] *= sx; f.bbox[3] *= sy
                    if hasattr(f, 'kps') and f.kps is not None:
                        f.kps[:, 0] *= sx
                        f.kps[:, 1] *= sy
            return faces_at_scale
        except Exception:
            return []

    def _detect_and_encode_faces(self, img_np: np.ndarray, is_bgr: bool = False) -> list[dict]:
        """
        Returns face records with BOTH arcface_vector and adaface_vector.

        FIX 3 — ArcFace + AdaFace run in PARALLEL using the thread pool.
        Previously they ran sequentially. On 2 vCPU this gives ~1.5x speedup
        since each model can use a separate core simultaneously.
        """
        if self.face_app is None:
            return []
        try:
            if img_np.dtype != np.uint8:
                img_np = (img_np * 255).astype(np.uint8)
            if is_bgr:
                bgr = img_np.copy()
            else:
                bgr = img_np[:, :, ::-1].copy() if (len(img_np.shape) == 3 and img_np.shape[2] == 3) else img_np.copy()
            bgr_enhanced = _clahe_enhance(bgr)
            H, W = bgr.shape[:2]

            all_raw_faces = self._run_detection_at_scale(bgr_enhanced, DET_SIZE_PRIMARY)

            if not all_raw_faces and ENABLE_MULTI_SCALE_FALLBACK:
                for scale in [(1280, 1280), (960, 960)]:
                    more = self._run_detection_at_scale(bgr_enhanced, scale)
                    all_raw_faces.extend(more)
                    if more:
                        break

            if ENABLE_HORIZONTAL_FLIP:
                bgr_flip = cv2.flip(bgr_enhanced, 1)
                # Reuse the aspect-ratio-preserving scaler so flipped detection
                # also avoids the wide-image squash.
                faces_flip = self._run_detection_at_scale(bgr_flip, DET_SIZE_PRIMARY)
                for f in faces_flip:
                    x1, y1, x2, y2 = f.bbox
                    f.bbox[0], f.bbox[2] = W - x2, W - x1
                    if hasattr(f, 'kps') and f.kps is not None:
                        f.kps[:, 0] = W - f.kps[:, 0]
                all_raw_faces.extend(faces_flip)

            self.face_app.det_model.input_size = DET_SIZE_PRIMARY
            faces = _dedup_faces(all_raw_faces)

            filtered_faces = []
            adaface_crops: list[np.ndarray | None] = []

            for face in faces:
                if len(filtered_faces) >= MAX_FACES_PER_IMAGE:
                    break
                bbox_raw = face.bbox.astype(int)
                x1, y1, x2, y2 = bbox_raw
                x1, y1 = max(0, x1), max(0, y1)
                x2, y2 = min(bgr.shape[1], x2), min(bgr.shape[0], y2)
                w, h = x2 - x1, y2 - y1
                if w < MIN_FACE_SIZE or h < MIN_FACE_SIZE:
                    continue
                det_score = float(face.det_score) if hasattr(face, "det_score") else 1.0
                if det_score < FACE_QUALITY_GATE or face.embedding is None:
                    continue
                blur = _blur_score(bgr, x1, y1, x2, y2)
                filtered_faces.append((face, x1, y1, x2, y2, w, h, det_score, blur))
                adaface_crops.append(_face_crop_for_adaface(bgr, x1, y1, x2, y2))

            if not filtered_faces:
                return []

            # ── FIX 3: Run ArcFace + AdaFace in PARALLEL ──────────────────────
            # Submit both to the thread pool simultaneously.
            # On 2 vCPU: total time ≈ max(arcface_time, adaface_time)
            # instead of arcface_time + adaface_time.
            face_objs = [f[0] for f in filtered_faces]

            arc_future = self._embed_pool.submit(
                self._arcface_embed_batch, face_objs, bgr
            )
            ada_future = self._embed_pool.submit(
                self._adaface_embed_batch, adaface_crops
            )

            # Wait for both — concurrent.futures blocks until done
            arcface_vecs = arc_future.result()
            adaface_vecs = ada_future.result()

            results = []
            for accepted, (face_tuple, arcface_vec, adaface_vec) in enumerate(
                zip(filtered_faces, arcface_vecs, adaface_vecs)
            ):
                face, x1, y1, x2, y2, w, h, det_score, blur_score = face_tuple

                out = {
                    "type": "face",
                    "face_idx": accepted,
                    "bbox": [int(x1), int(y1), int(w), int(h)],
                    "face_crop": _crop_to_b64(bgr, x1, y1, x2, y2),
                    "det_score": det_score,
                    "face_width_px": int(w),
                    "blur_score": blur_score,
                    "arcface_vector": arcface_vec,
                    "adaface_vector": adaface_vec if adaface_vec is not None
                                      else np.zeros(ADAFACE_DIM, dtype=np.float32),
                    "has_adaface": adaface_vec is not None,
                    "vector": arcface_vec,
                    "face_obj": face,
                }
                results.append(out)
            return results
        except Exception as _det_err:
            import traceback as _tb
            print(f"[_detect_and_encode_faces ERROR] shape={getattr(img_np, 'shape', 'N/A')}: {_det_err}")
            _tb.print_exc()
            return []

    # ── Main inference entry point ────────────────────────────────────────────
    def process_image_bytes(
        self, image_bytes: bytes, detect_faces: bool = True
    ) -> list[dict]:
        file_hash = hashlib.md5(image_bytes).hexdigest()
        cache_key = f"{file_hash}_{detect_faces}"

        with self._cache_lock:
            if cache_key in self._cache:
                return list(self._cache[cache_key])

        extracted = []
        original_pil = Image.open(io.BytesIO(image_bytes))
        # Apply EXIF orientation before anything else. Pillow does NOT do this
        # automatically — a portrait phone shot stored as landscape with a
        # rotation tag would feed sideways pixels to the face detector.
        original_pil = ImageOps.exif_transpose(original_pil)
        original_pil = original_pil.convert("RGB")
        img_np = np.array(original_pil)
        faces_found = False

        if detect_faces and self.face_app is not None:
            face_results = self._detect_and_encode_faces(img_np)
            if face_results:
                faces_found = True
                extracted.extend(face_results)

        crops: list[Image.Image] = []
        yolo_results = self.yolo(original_pil, conf=YOLO_CONF_THRESHOLD, verbose=False)

        for r in yolo_results:
            if r.masks is not None:
                for seg_idx, mask_xy in enumerate(r.masks.xy):
                    cls_id = int(r.boxes.cls[seg_idx].item())
                    if faces_found and cls_id == YOLO_PERSON_CLASS_ID:
                        continue
                    polygon = np.array(mask_xy, dtype=np.int32)
                    if len(polygon) < 3:
                        continue
                    x, y, w, h = cv2.boundingRect(polygon)
                    if w < YOLO_MIN_CROP_PX or h < YOLO_MIN_CROP_PX:
                        continue
                    crops.append(original_pil.crop((x, y, x + w, y + h)))
                    if len(crops) >= MAX_CROPS:
                        break
            elif r.boxes is not None:
                for box in r.boxes:
                    cls_id = int(box.cls.item())
                    if faces_found and cls_id == YOLO_PERSON_CLASS_ID:
                        continue
                    x1, y1, x2, y2 = box.xyxy[0].tolist()
                    if (x2 - x1) < YOLO_MIN_CROP_PX or (y2 - y1) < YOLO_MIN_CROP_PX:
                        continue
                    crops.append(original_pil.crop((x1, y1, x2, y2)))
            if len(crops) >= MAX_CROPS:
                break

        all_crops = [_resize_pil(c, MAX_IMAGE_SIZE) for c in [original_pil] + crops]
        obj_vecs = self._embed_crops_batch(all_crops)
        extracted.extend({"type": "object", "vector": v} for v in obj_vecs)

        with self._cache_lock:
            if len(self._cache) >= INFERENCE_CACHE_SIZE:
                oldest = next(iter(self._cache))
                del self._cache[oldest]
            self._cache[cache_key] = list(extracted)

        return extracted

    def extract_object_embedding(self, cv_img: np.ndarray) -> np.ndarray:
        """Extract visual scene / object embedding using SigLIP + DINOv2."""
        if cv_img is None or cv_img.size == 0:
            return np.array([], dtype=np.float32)
        rgb = cv_img[:, :, ::-1] if (len(cv_img.shape) == 3 and cv_img.shape[2] == 3) else cv_img
        pil = Image.fromarray(rgb)
        pil_resized = _resize_pil(pil, MAX_IMAGE_SIZE)
        vecs = self._embed_crops_batch([pil_resized])
        return vecs[0] if vecs else np.array([], dtype=np.float32)

    async def process_image_bytes_async(
        self, image_bytes: bytes, detect_faces: bool = True
    ) -> list[dict]:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            functools.partial(self.process_image_bytes, image_bytes, detect_faces),
        )