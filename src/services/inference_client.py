"""
src/services/inference_client.py — Unified Hybrid AI Inference Adapter.

Acts as a decoupled facade abstracting model execution:
1. If INFERENCE_BACKEND="triton", routes requests over high-speed async gRPC to NVIDIA Triton.
2. If INFERENCE_BACKEND="local" (or Triton is offline), gracefully falls back to local in-process AIModelManager.
Supports both asynchronous and synchronous caller contexts seamlessly.
"""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional
import cv2
import numpy as np

from src.core.config import INFERENCE_BACKEND, TRITON_SERVER_URL
from src.core.logging import log
from src.services.triton_inference_service import TritonInferenceService, TRITON_AVAILABLE

_inference_client_instance: Optional["InferenceClient"] = None


class InferenceClient:
    """
    Unified client abstraction supporting both decoupled NVIDIA Triton GPU inference
    and local CPU fallback via AIModelManager.
    """

    def __init__(self, backend: Optional[str] = None, triton_url: Optional[str] = None):
        self.backend = (backend or INFERENCE_BACKEND).lower()
        self.triton_url = triton_url or TRITON_SERVER_URL
        self._triton_service: Optional[TritonInferenceService] = None
        self._local_ai_manager: Optional[Any] = None
        self._thread_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="infer_sync")

        if self.backend == "triton" and TRITON_AVAILABLE:
            self._triton_service = TritonInferenceService(server_url=self.triton_url)

    def _get_local_ai_manager(self) -> Any:
        """Lazy-loads the local in-process AIModelManager when local fallback is needed."""
        if self._local_ai_manager is None:
            from src.services.ai_manager import AIModelManager
            self._local_ai_manager = AIModelManager()
            log("INFO", "inference.local_manager_loaded", message="Initialized in-process AIModelManager")
        return self._local_ai_manager

    def _run_sync(self, coro: Any) -> Any:
        """Safely executes a coroutine from synchronous caller contexts."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            # Already inside a running loop: run in separate thread to prevent loop blocking
            return self._thread_pool.submit(asyncio.run, coro).result()
        else:
            return asyncio.run(coro)

    async def is_triton_healthy(self) -> bool:
        """Verifies if the configured Triton service is reachable and ready."""
        if self._triton_service is None or not TRITON_AVAILABLE:
            return False
        try:
            return await self._triton_service.is_server_ready()
        except Exception:
            return False

    async def extract_face_embeddings(
        self,
        face_chip_bgr_or_dict: Any,
        aligned_chip_nchw: Optional[np.ndarray] = None,
        extract_adaface: bool = True,
    ) -> Dict[str, Any]:
        """
        Extracts ArcFace and optional AdaFace 512D embeddings.
        Returns dict with 'arcface_vector', 'adaface_vector', and 'has_adaface'.
        """
        # Resolve raw BGR crop if passed a dict
        crop_bgr = None
        if isinstance(face_chip_bgr_or_dict, dict):
            # Check for precomputed vectors
            if "arcface_vector" in face_chip_bgr_or_dict and face_chip_bgr_or_dict["arcface_vector"] is not None:
                raw_arc = face_chip_bgr_or_dict["arcface_vector"]
                arc_list = raw_arc.tolist() if hasattr(raw_arc, "tolist") else list(raw_arc)
                raw_ada = face_chip_bgr_or_dict.get("adaface_vector")
                ada_list = raw_ada.tolist() if hasattr(raw_ada, "tolist") else (list(raw_ada) if raw_ada is not None else None)
                return {
                    "arcface_vector": arc_list,
                    "adaface_vector": ada_list,
                    "has_adaface": face_chip_bgr_or_dict.get("has_adaface", bool(ada_list)),
                }
            crop_bgr = face_chip_bgr_or_dict.get("crop")
        elif isinstance(face_chip_bgr_or_dict, np.ndarray):
            crop_bgr = face_chip_bgr_or_dict

        # 1. Attempt Triton inference if enabled
        if self.backend == "triton" and self._triton_service is not None and crop_bgr is not None:
            try:
                # Ensure we have NCHW (1, 3, 112, 112) normalized tensor
                if aligned_chip_nchw is None:
                    resized = cv2.resize(crop_bgr, (112, 112))
                    rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)
                    tensor = (rgb.astype(np.float32) / 127.5) - 1.0
                    aligned_chip_nchw = tensor.transpose(2, 0, 1)

                arc_batch = await self._triton_service.extract_arcface_batch(aligned_chip_nchw)
                arc_vec = arc_batch[0].tolist() if len(arc_batch) > 0 else []

                ada_vec = None
                has_ada = False
                if extract_adaface:
                    try:
                        ada_batch = await self._triton_service.extract_adaface_batch(aligned_chip_nchw)
                        if len(ada_batch) > 0:
                            ada_vec = ada_batch[0].tolist()
                            has_ada = True
                    except Exception as ada_err:
                        log("DEBUG", "inference.triton.adaface_skipped", error=str(ada_err))

                return {
                    "arcface_vector": arc_vec,
                    "adaface_vector": ada_vec,
                    "has_adaface": has_ada,
                }
            except Exception as e:
                log("WARN", "inference.triton_failed_fallback_local", error=str(e), action="falling back to local AIModelManager")

        # 2. Local fallback via AIModelManager
        local_mgr = self._get_local_ai_manager()
        from src.modules.vision.face_embedder import extract_face_embeddings as local_extract
        return local_extract(local_mgr, face_chip_bgr_or_dict)

    def extract_face_embeddings_sync(
        self,
        face_chip_bgr_or_dict: Any,
        aligned_chip_nchw: Optional[np.ndarray] = None,
        extract_adaface: bool = True,
    ) -> Dict[str, Any]:
        """Synchronous wrapper for extract_face_embeddings."""
        if isinstance(face_chip_bgr_or_dict, dict) and "arcface_vector" in face_chip_bgr_or_dict and face_chip_bgr_or_dict["arcface_vector"] is not None:
            raw_arc = face_chip_bgr_or_dict["arcface_vector"]
            arc_list = raw_arc.tolist() if hasattr(raw_arc, "tolist") else list(raw_arc)
            raw_ada = face_chip_bgr_or_dict.get("adaface_vector")
            ada_list = raw_ada.tolist() if hasattr(raw_ada, "tolist") else (list(raw_ada) if raw_ada is not None else None)
            return {
                "arcface_vector": arc_list,
                "adaface_vector": ada_list,
                "has_adaface": face_chip_bgr_or_dict.get("has_adaface", bool(ada_list)),
            }

        if self.backend == "local" and self._triton_service is None:
            local_mgr = self._get_local_ai_manager()
            from src.modules.vision.face_embedder import extract_face_embeddings as local_extract
            return local_extract(local_mgr, face_chip_bgr_or_dict)
        return self._run_sync(self.extract_face_embeddings(face_chip_bgr_or_dict, aligned_chip_nchw, extract_adaface))

    async def extract_scene_embedding(self, cv_img: np.ndarray) -> List[float]:
        """
        Extracts 1536D multimodal scene embedding (SigLIP 768D + DINOv2 768D).
        """
        if self.backend == "triton" and self._triton_service is not None:
            try:
                resized = cv2.resize(cv_img, (224, 224))
                rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)
                normed = (rgb.astype(np.float32) / 255.0 - np.array([0.485, 0.456, 0.406])) / np.array([0.229, 0.224, 0.225])
                tensor = normed.transpose(2, 0, 1)

                fused_batch = await self._triton_service.extract_scene_embeddings(tensor)
                if len(fused_batch) > 0:
                    return fused_batch[0].tolist()
            except Exception as e:
                log("WARN", "inference.triton_scene_fallback", error=str(e), action="falling back to local AIModelManager")

        local_mgr = self._get_local_ai_manager()
        from src.modules.vision.object_embedder import extract_object_embedding as local_extract_scene
        return local_extract_scene(local_mgr, cv_img)

    def extract_scene_embedding_sync(self, cv_img: np.ndarray) -> List[float]:
        """Synchronous wrapper for extract_scene_embedding."""
        if self.backend == "local" and self._triton_service is None:
            local_mgr = self._get_local_ai_manager()
            from src.modules.vision.object_embedder import extract_object_embedding as local_extract_scene
            return local_extract_scene(local_mgr, cv_img)
        return self._run_sync(self.extract_scene_embedding(cv_img))

    async def detect_faces(self, cv_img: np.ndarray, min_blur: float = 15.0) -> List[Dict[str, Any]]:
        """
        Detects faces, landmarks, and extracts aligned bounding boxes.
        """
        if self.backend == "triton" and self._triton_service is not None:
            try:
                dets = await self._triton_service.detect_faces_scrfd(cv_img)
                valid = []
                for idx, det in enumerate(dets):
                    bbox = det["bbox"]
                    x1, y1, x2, y2 = bbox
                    crop = cv_img[y1:y2, x1:x2]
                    if crop.size == 0:
                        continue
                    from src.modules.vision.image_quality import compute_blur_score
                    blur_score = compute_blur_score(crop)
                    if blur_score < min_blur:
                        continue
                    det["face_idx"] = idx
                    det["blur_score"] = blur_score
                    det["crop"] = crop
                    valid.append(det)
                return valid
            except Exception as e:
                log("WARN", "inference.triton_det_fallback", error=str(e), action="falling back to local AIModelManager")

        local_mgr = self._get_local_ai_manager()
        from src.modules.vision.face_detector import detect_faces as local_detect
        return local_detect(local_mgr, cv_img, min_blur=min_blur)

    def detect_faces_sync(self, cv_img: np.ndarray, min_blur: float = 15.0) -> List[Dict[str, Any]]:
        """Synchronous wrapper for detect_faces."""
        if self.backend == "local" and self._triton_service is None:
            local_mgr = self._get_local_ai_manager()
            from src.modules.vision.face_detector import detect_faces as local_detect
            return local_detect(local_mgr, cv_img, min_blur=min_blur)
        return self._run_sync(self.detect_faces(cv_img, min_blur=min_blur))

    async def close(self):
        """Closes the underlying Triton connection if active."""
        if self._triton_service is not None:
            await self._triton_service.close()
        self._thread_pool.shutdown(wait=False)


def get_inference_client() -> InferenceClient:
    """Thread-safe singleton getter for the InferenceClient."""
    global _inference_client_instance
    if _inference_client_instance is None:
        _inference_client_instance = InferenceClient()
    return _inference_client_instance
