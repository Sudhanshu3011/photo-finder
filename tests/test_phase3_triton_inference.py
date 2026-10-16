"""
tests/test_phase3_triton_inference.py — Test Suite for Phase 3 Triton Inference Decoupling.

Verifies:
1. Mathematical normalization (L2) and tensor preparation.
2. Triton gRPC client serialization, batching, and mock responses.
3. Scene embedding fusion (SigLIP 768D + DINOv2 768D -> 1536D).
4. Dual-mode fallback in InferenceClient (Triton vs Local AIModelManager).
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import numpy as np
import pytest

import src.services.triton_inference_service as triton_mod
from src.core.config import (
    INFERENCE_BACKEND,
    TRITON_SERVER_URL,
    TRITON_MODEL_ARCFACE,
    TRITON_MODEL_DINOV2,
    TRITON_MODEL_SIGLIP,
    TRITON_MODEL_SCRFD,
)
from src.services.inference_client import InferenceClient, get_inference_client
from src.services.triton_inference_service import (
    TritonInferenceService,
    _l2_normalize,
    _letterbox_image,
)


# Helper dummy classes to simulate tritonclient when not installed in test runner
class DummyInferInput:
    def __init__(self, name, shape, datatype):
        self.name = name
        self.shape = shape
        self.datatype = datatype
        self.data = None

    def set_data_from_numpy(self, arr):
        self.data = arr


class DummyInferRequestedOutput:
    def __init__(self, name):
        self.name = name


@pytest.fixture(autouse=True)
def mock_triton_client_classes():
    """Ensure tritonclient mock classes are available even if package is not installed."""
    mock_grpc = MagicMock()
    mock_grpc.InferInput = DummyInferInput
    mock_grpc.InferRequestedOutput = DummyInferRequestedOutput

    with patch.object(triton_mod, "TRITON_AVAILABLE", True), \
         patch.object(triton_mod, "grpcclient", mock_grpc):
        yield


def test_l2_normalize():
    """Verify that _l2_normalize produces unit vectors."""
    # 1D vector
    v1 = np.array([3.0, 4.0], dtype=np.float32)
    normed1 = _l2_normalize(v1)
    assert np.isclose(np.linalg.norm(normed1), 1.0, atol=1e-5)
    assert np.isclose(normed1[0], 0.6)
    assert np.isclose(normed1[1], 0.8)

    # 2D batch
    v2 = np.array([[1.0, 1.0, 1.0, 1.0], [0.0, 5.0, 0.0, 0.0]], dtype=np.float32)
    normed2 = _l2_normalize(v2)
    for row in normed2:
        assert np.isclose(np.linalg.norm(row), 1.0, atol=1e-5)


def test_letterbox_image():
    """Verify aspect ratio preservation and padding."""
    dummy_img = np.zeros((300, 600, 3), dtype=np.uint8)
    canvas, scale, (pad_w, pad_h) = _letterbox_image(dummy_img, (640, 640))

    assert canvas.shape == (640, 640, 3)
    assert scale > 0
    assert pad_h > 0


@pytest.mark.asyncio
async def test_triton_service_is_server_ready():
    """Test server readiness probe with mocked gRPC client."""
    service = TritonInferenceService(server_url="test:8001")

    mock_client = AsyncMock()
    mock_client.is_server_ready = AsyncMock(return_value=True)

    with patch.object(service, "get_client", AsyncMock(return_value=mock_client)):
        ready = await service.is_server_ready()
        assert ready is True
        mock_client.is_server_ready.assert_awaited_once()


@pytest.mark.asyncio
async def test_triton_extract_arcface_batch():
    """Test ArcFace batch inference with mocked response."""
    service = TritonInferenceService(server_url="test:8001")

    raw_emb = np.random.randn(2, 512).astype(np.float32)
    mock_response = MagicMock()
    mock_response.as_numpy.return_value = raw_emb

    mock_client = AsyncMock()
    mock_client.infer = AsyncMock(return_value=mock_response)

    with patch.object(service, "get_client", AsyncMock(return_value=mock_client)):
        dummy_chips = np.random.randn(2, 3, 112, 112).astype(np.float32)
        result = await service.extract_arcface_batch(dummy_chips)

        assert result.shape == (2, 512)
        assert np.isclose(np.linalg.norm(result[0]), 1.0, atol=1e-5)
        assert np.isclose(np.linalg.norm(result[1]), 1.0, atol=1e-5)
        mock_client.infer.assert_awaited_once()


@pytest.mark.asyncio
async def test_triton_extract_scene_embeddings_fusion():
    """Test DINOv2 + SigLIP multimodal fusion (768D + 768D -> 1536D)."""
    service = TritonInferenceService(server_url="test:8001")

    dino_raw = np.random.randn(1, 1, 768).astype(np.float32)
    dino_mock = MagicMock()
    dino_mock.as_numpy.return_value = dino_raw

    siglip_raw = np.random.randn(1, 1, 768).astype(np.float32)
    siglip_mock = MagicMock()
    siglip_mock.as_numpy.return_value = siglip_raw

    mock_client = AsyncMock()
    mock_client.infer = AsyncMock(side_effect=[dino_mock, siglip_mock])

    with patch.object(service, "get_client", AsyncMock(return_value=mock_client)):
        dummy_tensor = np.random.randn(1, 3, 224, 224).astype(np.float32)
        fused = await service.extract_scene_embeddings(dummy_tensor)

        assert fused.shape == (1, 1536)
        assert np.isclose(np.linalg.norm(fused[0]), 1.0, atol=1e-5)
        assert mock_client.infer.await_count == 2


@pytest.mark.asyncio
async def test_inference_client_local_fallback_on_triton_error():
    """Verify that InferenceClient smoothly falls back to local manager if Triton fails."""
    client = InferenceClient(backend="triton")
    client._local_ai_manager = MagicMock()

    mock_triton = AsyncMock()
    mock_triton.extract_arcface_batch.side_effect = ConnectionError("Triton server unavailable")
    client._triton_service = mock_triton

    dummy_face_bgr = np.zeros((112, 112, 3), dtype=np.uint8)
    mock_local_extract = MagicMock(return_value={
        "arcface_vector": [0.1] * 512,
        "adaface_vector": None,
        "has_adaface": False,
    })

    with patch("src.modules.vision.face_embedder.extract_face_embeddings", mock_local_extract):
        result = await client.extract_face_embeddings(dummy_face_bgr)
        assert len(result["arcface_vector"]) == 512
        assert result["has_adaface"] is False
        mock_local_extract.assert_called_once()


@pytest.mark.asyncio
async def test_inference_client_local_backend_direct():
    """Verify that when INFERENCE_BACKEND='local', Triton is never invoked."""
    client = InferenceClient(backend="local")
    client._local_ai_manager = MagicMock()
    assert client.backend == "local"
    assert client._triton_service is None

    dummy_face_bgr = np.zeros((112, 112, 3), dtype=np.uint8)
    mock_local_extract = MagicMock(return_value={
        "arcface_vector": [0.5] * 512,
        "adaface_vector": None,
        "has_adaface": False,
    })

    with patch("src.modules.vision.face_embedder.extract_face_embeddings", mock_local_extract):
        result = await client.extract_face_embeddings(dummy_face_bgr)
        assert len(result["arcface_vector"]) == 512
        mock_local_extract.assert_called_once()


def test_inference_client_singleton():
    """Verify singleton getter returns the same instance."""
    inst1 = get_inference_client()
    inst2 = get_inference_client()
    assert inst1 is inst2


def test_image_search_service_routes_through_inference_client():
    """Verify ImageSearchService executes face and scene queries via inference_client."""
    mock_infer = MagicMock()
    mock_infer.detect_faces_sync.return_value = [
        {"face_idx": 0, "bbox": [10, 10, 50, 50], "crop": np.zeros((40, 40, 3), dtype=np.uint8)}
    ]
    mock_infer.extract_face_embeddings_sync.return_value = {
        "arcface_vector": [0.1] * 512,
        "adaface_vector": [0.2] * 512,
        "has_adaface": True,
    }

    mock_engine = MagicMock()
    mock_engine.search_vectors.return_value = [
        {"id": "face_img1_0", "score": 0.95, "metadata": {"image_id": "img1", "folder": "general"}}
    ]

    from src.services.image_search_service import ImageSearchService
    search_svc = ImageSearchService(engine=mock_engine, inference_client=mock_infer)

    dummy_query = np.zeros((100, 100, 3), dtype=np.uint8)
    res = search_svc.search_by_image(dummy_query, tenant_id="tenant_test")

    assert res["query_type"] == "face"
    assert res["total_matches"] > 0
    mock_infer.detect_faces_sync.assert_called_once()
    mock_infer.extract_face_embeddings_sync.assert_called_once()


def test_image_processing_service_routes_through_inference_client():
    """Verify ImageProcessingService ingests vectors using inference_client."""
    mock_infer = MagicMock()
    mock_infer.detect_faces_sync.return_value = [
        {"face_idx": 0, "bbox": [10, 10, 50, 50], "crop": np.zeros((40, 40, 3), dtype=np.uint8), "blur_score": 50.0}
    ]
    mock_infer.extract_face_embeddings_sync.return_value = {
        "arcface_vector": [0.3] * 512,
        "adaface_vector": [0.4] * 512,
        "has_adaface": True,
    }
    mock_infer.extract_scene_embedding_sync.return_value = [0.05] * 1536

    mock_engine = MagicMock()
    from src.services.image_processing_service import ImageProcessingService
    proc_svc = ImageProcessingService(engine=mock_engine, inference_client=mock_infer)

    dummy_img = np.zeros((100, 100, 3), dtype=np.uint8)
    result = proc_svc.process_image_cv(
        image_id="test_img_123",
        cv_img=dummy_img,
        tenant_id="tenant_test"
    )

    assert result["status"] == "success"
    assert result["faces_detected"] == 1
    assert result["objects_detected"] == 1
    mock_infer.detect_faces_sync.assert_called_once()
    mock_infer.extract_face_embeddings_sync.assert_called_once()
    mock_infer.extract_scene_embedding_sync.assert_called_once()


