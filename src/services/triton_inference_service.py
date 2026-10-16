"""
src/services/triton_inference_service.py — High-Performance Asynchronous gRPC Client for NVIDIA Triton.

Provides low-latency, binary tensor serialization and dynamic batching communication
with the decoupled Triton Inference Server over HTTP/2 gRPC.
"""
import asyncio
from typing import Any, Dict, List, Optional, Tuple
import cv2
import numpy as np

from src.core.config import (
    TRITON_SERVER_URL,
    TRITON_TIMEOUT_SECONDS,
    TRITON_MODEL_ARCFACE,
    TRITON_MODEL_ADAFACE,
    TRITON_MODEL_DINOV2,
    TRITON_MODEL_SIGLIP,
    TRITON_MODEL_SCRFD,
)
from src.core.logging import log

try:
    import tritonclient.grpc.aio as grpcclient
    TRITON_AVAILABLE = True
except ImportError:
    grpcclient = None
    TRITON_AVAILABLE = False


def _l2_normalize(vectors: np.ndarray, eps: float = 1e-12) -> np.ndarray:
    """Computes row-wise unit Euclidean (L2) normalization."""
    if vectors.ndim == 1:
        norm = np.linalg.norm(vectors)
        return vectors / max(norm, eps)
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    norms = np.maximum(norms, eps)
    return vectors / norms


def _letterbox_image(img: np.ndarray, target_size: Tuple[int, int] = (640, 640)) -> Tuple[np.ndarray, float, Tuple[int, int]]:
    """Resizes and letterboxes image to target (W, H) preserving aspect ratio."""
    h, w = img.shape[:2]
    tw, th = target_size
    scale = min(tw / w, th / h)
    nw, nh = int(round(w * scale)), int(round(h * scale))
    resized = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_LINEAR)

    canvas = np.zeros((th, tw, 3), dtype=np.uint8)
    pad_w = (tw - nw) // 2
    pad_h = (th - nh) // 2
    canvas[pad_h:pad_h + nh, pad_w:pad_w + nw] = resized
    return canvas, scale, (pad_w, pad_h)


class TritonInferenceService:
    """
    Asynchronous gRPC client communicating with NVIDIA Triton Inference Server.
    Supports continuous dynamic batching, binary tensor input/output, and auto-reconnect.
    """

    def __init__(self, server_url: Optional[str] = None, timeout: float = TRITON_TIMEOUT_SECONDS):
        self.server_url = server_url or TRITON_SERVER_URL
        self.timeout = timeout
        self._client: Optional[Any] = None
        self._lock = asyncio.Lock()

    async def get_client(self) -> Any:
        """Returns or creates a persistent async gRPC client channel."""
        if not TRITON_AVAILABLE:
            raise RuntimeError("tritonclient[grpc] is not installed. Install via pip install tritonclient[grpc].")

        if self._client is None:
            async with self._lock:
                if self._client is None:
                    self._client = grpcclient.InferenceServerClient(
                        url=self.server_url,
                        verbose=False,
                    )
        return self._client

    async def is_server_ready(self) -> bool:
        """Pings the Triton server to verify overall server liveness & readiness."""
        if not TRITON_AVAILABLE:
            return False
        try:
            client = await self.get_client()
            return await asyncio.wait_for(client.is_server_ready(), timeout=self.timeout)
        except Exception as e:
            log("DEBUG", "triton.health_check_failed", error=str(e), server_url=self.server_url)
            return False

    async def is_model_ready(self, model_name: str) -> bool:
        """Checks if a specific model version is loaded and healthy in Triton."""
        if not TRITON_AVAILABLE:
            return False
        try:
            client = await self.get_client()
            return await asyncio.wait_for(client.is_model_ready(model_name=model_name), timeout=self.timeout)
        except Exception as e:
            log("DEBUG", "triton.model_health_failed", model_name=model_name, error=str(e))
            return False

    async def extract_arcface_batch(self, aligned_chips_nchw: np.ndarray) -> np.ndarray:
        """
        Extracts 512D ArcFace embeddings from batch of aligned face chips.
        Input:  (B, 3, 112, 112) float32 normalized face chips.
        Output: (B, 512) float32 unit-normalized (L2) embeddings.
        """
        chips = np.ascontiguousarray(aligned_chips_nchw, dtype=np.float32)
        if chips.ndim == 3:
            chips = np.expand_dims(chips, axis=0)

        client = await self.get_client()

        inputs = [grpcclient.InferInput("input_0", chips.shape, "FP32")]
        inputs[0].set_data_from_numpy(chips)

        outputs = [grpcclient.InferRequestedOutput("output_0")]

        response = await asyncio.wait_for(
            client.infer(model_name=TRITON_MODEL_ARCFACE, inputs=inputs, outputs=outputs),
            timeout=self.timeout,
        )

        embeddings = response.as_numpy("output_0")
        return _l2_normalize(embeddings)

    async def extract_adaface_batch(self, aligned_chips_nchw: np.ndarray) -> np.ndarray:
        """
        Extracts 512D AdaFace embeddings from batch of quality-adaptive face chips.
        Input:  (B, 3, 112, 112) float32 normalized face chips.
        Output: (B, 512) float32 unit-normalized (L2) embeddings.
        """
        chips = np.ascontiguousarray(aligned_chips_nchw, dtype=np.float32)
        if chips.ndim == 3:
            chips = np.expand_dims(chips, axis=0)

        client = await self.get_client()

        inputs = [grpcclient.InferInput("input_0", chips.shape, "FP32")]
        inputs[0].set_data_from_numpy(chips)

        outputs = [grpcclient.InferRequestedOutput("output_0")]

        response = await asyncio.wait_for(
            client.infer(model_name=TRITON_MODEL_ADAFACE, inputs=inputs, outputs=outputs),
            timeout=self.timeout,
        )

        embeddings = response.as_numpy("output_0")
        return _l2_normalize(embeddings)

    async def extract_scene_embeddings(self, preprocessed_chw: np.ndarray) -> np.ndarray:
        """
        Extracts 1536D scene embeddings by querying DINOv2 and SigLIP concurrently over gRPC.
        Input:  (B, 3, 224, 224) float32 normalized image tensors.
        Output: (B, 1536) float32 fused L2-normalized embeddings.
        """
        tensors = np.ascontiguousarray(preprocessed_chw, dtype=np.float32)
        if tensors.ndim == 3:
            tensors = np.expand_dims(tensors, axis=0)

        client = await self.get_client()

        # 1. Prepare Inputs for both DINOv2 and SigLIP
        dino_inputs = [grpcclient.InferInput("pixel_values", tensors.shape, "FP32")]
        dino_inputs[0].set_data_from_numpy(tensors)
        dino_outputs = [grpcclient.InferRequestedOutput("last_hidden_state")]

        siglip_inputs = [grpcclient.InferInput("pixel_values", tensors.shape, "FP32")]
        siglip_inputs[0].set_data_from_numpy(tensors)
        siglip_outputs = [grpcclient.InferRequestedOutput("last_hidden_state")]

        # 2. Query both vision transformers concurrently
        dino_task = client.infer(model_name=TRITON_MODEL_DINOV2, inputs=dino_inputs, outputs=dino_outputs)
        siglip_task = client.infer(model_name=TRITON_MODEL_SIGLIP, inputs=siglip_inputs, outputs=siglip_outputs)

        dino_res, siglip_res = await asyncio.wait_for(
            asyncio.gather(dino_task, siglip_task),
            timeout=self.timeout,
        )

        # 3. Extract CLS features (768D) from each output tensor
        dino_out = dino_res.as_numpy("last_hidden_state")
        siglip_out = siglip_res.as_numpy("last_hidden_state")

        if dino_out.ndim == 3:
            dino_vec = dino_out[:, 0, :]  # Extract CLS token
        else:
            dino_vec = dino_out

        if siglip_out.ndim == 3:
            siglip_vec = siglip_out[:, 0, :]
        else:
            siglip_vec = siglip_out

        dino_vec = _l2_normalize(dino_vec)
        siglip_vec = _l2_normalize(siglip_vec)

        # 4. Concatenate into 1536D fused representation & normalize
        fused = np.concatenate([siglip_vec, dino_vec], axis=1)
        return _l2_normalize(fused)

    async def detect_faces_scrfd(
        self, image_bgr: np.ndarray, score_threshold: float = 0.5
    ) -> List[Dict[str, Any]]:
        """
        Executes face detection and 5-point landmark localization using SCRFD on Triton.
        Returns list of dicts with 'bbox' [x1, y1, x2, y2], 'det_score', and 'kps' (landmarks).
        """
        orig_h, orig_w = image_bgr.shape[:2]
        canvas, scale, (pad_w, pad_h) = _letterbox_image(image_bgr, (640, 640))

        # Standard InsightFace SCRFD normalization: (canvas - 127.5) / 128.0, transpose to NCHW
        blob = canvas.astype(np.float32)
        blob = (blob - 127.5) / 128.0
        blob = blob.transpose(2, 0, 1)
        blob = np.expand_dims(blob, axis=0)
        blob = np.ascontiguousarray(blob, dtype=np.float32)

        client = await self.get_client()

        inputs = [grpcclient.InferInput("input.1", blob.shape, "FP32")]
        inputs[0].set_data_from_numpy(blob)

        # Outputs across strides 8, 16, 32
        output_names = [
            "score_8", "score_16", "score_32",
            "bbox_8", "bbox_16", "bbox_32",
            "kps_8", "kps_16", "kps_32"
        ]
        outputs = [grpcclient.InferRequestedOutput(name) for name in output_names]

        response = await asyncio.wait_for(
            client.infer(model_name=TRITON_MODEL_SCRFD, inputs=inputs, outputs=outputs),
            timeout=self.timeout,
        )

        detections = []
        for stride in [8, 16, 32]:
            scores = response.as_numpy(f"score_{stride}")
            bboxes = response.as_numpy(f"bbox_{stride}")
            kps = response.as_numpy(f"kps_{stride}")

            if scores is None or bboxes is None:
                continue

            scores = scores.reshape(-1)
            bboxes = bboxes.reshape(-1, 4)
            kps_reshaped = kps.reshape(-1, 5, 2) if kps is not None else None

            valid_mask = scores >= score_threshold
            for idx in np.where(valid_mask)[0]:
                score = float(scores[idx])
                box = bboxes[idx] * stride
                # Unpad and scale back to original image dimensions
                x1 = int(round((box[0] - pad_w) / scale))
                y1 = int(round((box[1] - pad_h) / scale))
                x2 = int(round((box[2] - pad_w) / scale))
                y2 = int(round((box[3] - pad_h) / scale))

                x1, y1 = max(0, x1), max(0, y1)
                x2, y2 = min(orig_w, x2), min(orig_h, y2)

                det = {
                    "det_score": score,
                    "bbox": [x1, y1, x2, y2],
                }
                if kps_reshaped is not None:
                    kp = kps_reshaped[idx] * stride
                    unpadded_kp = []
                    for pt in kp:
                        px = float((pt[0] - pad_w) / scale)
                        py = float((pt[1] - pad_h) / scale)
                        unpadded_kp.append([px, py])
                    det["kps"] = unpadded_kp

                detections.append(det)

        return detections

    async def close(self):
        """Closes the underlying gRPC client channel gracefully."""
        if self._client is not None:
            try:
                await self._client.close()
            except Exception as e:
                log("DEBUG", "triton.client_close_error", error=str(e))
            finally:
                self._client = None

