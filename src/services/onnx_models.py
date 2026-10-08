"""
ONNX runtime wrappers. Drop-in replacement for the PyTorch SigLIP + DINOv2
models inside AIModelManager._embed_crops_batch.

Import pattern in ai_manager.py:

    from src.services.onnx_models import ONNXVisionStack
    if USE_ONNX_VISION:
        self.vision_stack = ONNXVisionStack(ONNX_MODELS_DIR, ONNX_USE_INT8)
        # use self.vision_stack.encode(crops) instead of torch models
"""
import os
import numpy as np
from PIL import Image
import onnxruntime as ort


# SigLIP normalization (ImageNet-style mean/std for siglip-base-patch16-224)
_SIGLIP_MEAN = np.array([0.5, 0.5, 0.5], dtype=np.float32)
_SIGLIP_STD = np.array([0.5, 0.5, 0.5], dtype=np.float32)

# DINOv2 uses ImageNet stats
_DINO_MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
_DINO_STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)


def _preprocess_batch(
    pil_images: list[Image.Image], size: int, mean: np.ndarray, std: np.ndarray
) -> np.ndarray:
    """Resize + normalize a batch of PIL images to (B, 3, size, size) fp32."""
    arrs = []
    for im in pil_images:
        if im.mode != "RGB":
            im = im.convert("RGB")
        im = im.resize((size, size), Image.BILINEAR)
        a = np.asarray(im, dtype=np.float32) / 255.0
        a = (a - mean) / std
        a = a.transpose(2, 0, 1)  # HWC -> CHW
        arrs.append(a)
    return np.stack(arrs, axis=0)


def _l2_normalize(x: np.ndarray, axis: int = 1) -> np.ndarray:
    n = np.linalg.norm(x, axis=axis, keepdims=True)
    n = np.where(n == 0, 1.0, n)
    return x / n


class ONNXVisionStack:
    """SigLIP + DINOv2 fused embeddings via ONNX Runtime (CPU)."""

    def __init__(self, models_dir: str, use_int8: bool = True):
        siglip_name = "siglip_vision_int8.onnx" if use_int8 else "siglip_vision.onnx"
        dino_name = "dinov2_int8.onnx" if use_int8 else "dinov2.onnx"

        siglip_path = os.path.join(models_dir, siglip_name)
        dino_path = os.path.join(models_dir, dino_name)

        if not os.path.exists(siglip_path):
            raise FileNotFoundError(
                f"ONNX model not found: {siglip_path}. "
                "Run scripts/convert_to_onnx.py and upload outputs to the Space."
            )
        if not os.path.exists(dino_path):
            raise FileNotFoundError(f"ONNX model not found: {dino_path}")

        sess_opts = ort.SessionOptions()
        sess_opts.intra_op_num_threads = int(os.getenv("OMP_NUM_THREADS", "2"))
        sess_opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL

        self.siglip = ort.InferenceSession(
            siglip_path, sess_options=sess_opts, providers=["CPUExecutionProvider"]
        )
        self.dino = ort.InferenceSession(
            dino_path, sess_options=sess_opts, providers=["CPUExecutionProvider"]
        )

        # Warmup — first call is always slow due to kernel compilation
        dummy = np.zeros((1, 3, 224, 224), dtype=np.float32)
        self.siglip.run(None, {"pixel_values": dummy})
        self.dino.run(None, {"pixel_values": dummy})

    def encode(self, pil_crops: list[Image.Image]) -> list[np.ndarray]:
        """Returns list of 1536-d L2-normalized fused vectors (same shape as old code)."""
        if not pil_crops:
            return []

        sig_batch = _preprocess_batch(pil_crops, 224, _SIGLIP_MEAN, _SIGLIP_STD)
        dino_batch = _preprocess_batch(pil_crops, 224, _DINO_MEAN, _DINO_STD)

        sig_out = self.siglip.run(None, {"pixel_values": sig_batch})[0]  # (B, 768)
        dino_out = self.dino.run(None, {"pixel_values": dino_batch})[0]  # (B, 768)

        sig_n = _l2_normalize(sig_out)
        dino_n = _l2_normalize(dino_out)

        fused = np.concatenate([sig_n, dino_n], axis=1)  # (B, 1536)
        fused = _l2_normalize(fused)

        return [fused[i] for i in range(fused.shape[0])]