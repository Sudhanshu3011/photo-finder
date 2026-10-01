"""
tests/unit/test_faiss_service.py — Unit tests for local FAISS Vector Storage Engine.
Validates:
- Vector upsert and normalization
- Exact Cosine Similarity ranking
- Metadata persistence in SQLite
- ID-based deletion
- URL-based and folder-based deletion
- Index reset
"""
import os
import shutil
import pytest
import numpy as np

from src.services.faiss_service import FAISSVectorStore


@pytest.fixture
def temp_faiss_store(tmp_path):
    """Creates an isolated FAISSVectorStore inside a temporary directory."""
    store = FAISSVectorStore(data_dir=str(tmp_path / "faiss"))
    yield store
    store.reset_all()


def test_upsert_and_search_cosine_similarity(temp_faiss_store):
    """Verify that normalized vector search returns the closest match with highest cosine similarity."""
    test_index = "test_faces"

    # Vector A: [1.0, 0.0, 0.0]
    # Vector B: [0.0, 1.0, 0.0]
    # Vector C: [0.707, 0.707, 0.0]
    vectors = [
        {
            "id": "face_a",
            "values": [1.0, 0.0, 0.0],
            "metadata": {"url": "https://img.com/a.jpg", "folder": "trip"},
        },
        {
            "id": "face_b",
            "values": [0.0, 1.0, 0.0],
            "metadata": {"url": "https://img.com/b.jpg", "folder": "trip"},
        },
        {
            "id": "face_c",
            "values": [0.707, 0.707, 0.0],
            "metadata": {"url": "https://img.com/c.jpg", "folder": "party"},
        },
    ]

    count = temp_faiss_store.upsert_vectors(test_index, vectors)
    assert count == 3

    # Query with [1.0, 0.0, 0.0] — should rank face_a first (score ~1.0)
    matches = temp_faiss_store.search(test_index, [1.0, 0.0, 0.0], top_k=2)
    assert len(matches) == 2
    assert matches[0]["id"] == "face_a"
    assert matches[0]["score"] > 0.99
    assert matches[0]["metadata"]["url"] == "https://img.com/a.jpg"


def test_search_with_metadata_filter(temp_faiss_store):
    """Verify filtering matches by folder."""
    test_index = "test_faces"

    vectors = [
        {"id": "img_1", "values": [1.0, 0.0], "metadata": {"folder": "events"}},
        {"id": "img_2", "values": [0.9, 0.1], "metadata": {"folder": "travel"}},
    ]
    temp_faiss_store.upsert_vectors(test_index, vectors)

    filtered = temp_faiss_store.search(
        test_index, [1.0, 0.0], top_k=5, filter_dict={"folder": "travel"}
    )
    assert len(filtered) == 1
    assert filtered[0]["id"] == "img_2"


def test_delete_by_id(temp_faiss_store):
    """Verify deleting vectors by ID."""
    test_index = "test_faces"
    vectors = [
        {"id": "v1", "values": [0.5, 0.5], "metadata": {"url": "u1"}},
        {"id": "v2", "values": [0.2, 0.8], "metadata": {"url": "u2"}},
    ]
    temp_faiss_store.upsert_vectors(test_index, vectors)

    deleted = temp_faiss_store.delete_by_ids(test_index, ["v1"])
    assert deleted == 1

    remaining = temp_faiss_store.search(test_index, [0.5, 0.5], top_k=5)
    remaining_ids = [m["id"] for m in remaining]
    assert "v1" not in remaining_ids
    assert "v2" in remaining_ids


def test_delete_by_url(temp_faiss_store):
    """Verify deleting vectors across indexes by image URL."""
    test_index = "test_faces"
    vectors = [
        {"id": "v_url_1", "values": [0.6, 0.4], "metadata": {"url": "https://img.com/delete_me.jpg"}},
        {"id": "v_url_2", "values": [0.1, 0.9], "metadata": {"url": "https://img.com/keep_me.jpg"}},
    ]
    temp_faiss_store.upsert_vectors(test_index, vectors)

    deleted = temp_faiss_store.delete_by_url("https://img.com/delete_me.jpg")
    assert deleted >= 1

    remaining = temp_faiss_store.search(test_index, [0.6, 0.4], top_k=5)
    remaining_urls = [m["metadata"]["url"] for m in remaining]
    assert "https://img.com/delete_me.jpg" not in remaining_urls
