"""
src/services/upload_service.py — Business logic for image uploads and FAISS vector indexing.
Extracted from API router layer to adhere to MVC and Clean Architecture.
Decouples fast image ingestion (Cloudinary) from asynchronous AI model inference and FAISS indexing.
"""
import asyncio
import io
import os
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

from src.core.config import (
    IDX_FACES, IDX_OBJECTS,
    IDX_FACES_ARCFACE, IDX_FACES_ADAFACE,
    MAX_FILES_PER_UPLOAD, USE_SPLIT_FACE_INDEXES,
    USE_ASYNC_UPLOADS, CLUSTER_AUTO_TRIGGER_EVERY,
)
from src.core.logging import log
from src.common.utils import standardize_category_name, to_list
from src.services.cloudinary_service import cld_upload
from src.services.faiss_service import faiss_store


def chunker(seq, size):
    """Yield successive chunks from seq of size."""
    return (seq[pos:pos + size] for pos in range(0, len(seq), size))


async def process_one_file(
    *,
    file_bytes: bytes,
    folder: str,
    detect_faces: bool,
    keys: dict,
    ai,
    sem,
) -> Tuple[str, str, list]:
    """Uploads image to Cloudinary and runs AI inference concurrently (used for synchronous fallback)."""
    file_id = uuid.uuid4().hex

    async def _run_ai():
        async with sem:
            return await ai.process_image_bytes_async(file_bytes, detect_faces=detect_faces)

    cld_task = asyncio.to_thread(
        cld_upload, io.BytesIO(file_bytes), folder, keys["cloudinary_creds"]
    )
    ai_task = _run_ai()
    cld_res, vectors = await asyncio.gather(cld_task, ai_task)
    return file_id, cld_res["secure_url"], vectors


async def batch_upsert_all(
    *, results: list, folder: str, vector_store=None,
) -> dict:
    """Takes [(file_id, url, vectors), ...] and upserts batches into local FAISS indexes."""
    store = vector_store or faiss_store

    arcface_upserts = []
    adaface_upserts = []
    legacy_face_upserts = []
    object_upserts = []
    uploaded_urls = []

    for file_id, image_url, vectors in results:
        uploaded_urls.append(image_url)
        for i, v in enumerate(vectors):
            vector_id = f"{file_id}_{i}"

            if v["type"] == "face":
                meta_common = {
                    "url": image_url,
                    "folder": folder,
                    "face_crop": v.get("face_crop", ""),
                    "det_score": float(v.get("det_score", 1.0)),
                    "face_width_px": int(v.get("face_width_px", 0)),
                    "blur_score": float(v.get("blur_score", 100.0)),
                }
                if USE_SPLIT_FACE_INDEXES:
                    arcface_upserts.append({
                        "id": vector_id,
                        "values": to_list(v["arcface_vector"]),
                        "metadata": meta_common,
                    })
                    if v.get("has_adaface"):
                        adaface_upserts.append({
                            "id": vector_id,
                            "values": to_list(v["adaface_vector"]),
                            "metadata": meta_common,
                        })
                else:
                    legacy_face_upserts.append({
                        "id": vector_id,
                        "values": to_list(v["vector"]),
                        "metadata": meta_common,
                    })
            else:
                object_upserts.append({
                    "id": vector_id,
                    "values": to_list(v["vector"]),
                    "metadata": {"url": image_url, "folder": folder},
                })

    # Direct FAISS batch upsert
    if USE_SPLIT_FACE_INDEXES:
        if arcface_upserts:
            store.upsert_vectors(IDX_FACES_ARCFACE, arcface_upserts)
        if adaface_upserts:
            store.upsert_vectors(IDX_FACES_ADAFACE, adaface_upserts)
    else:
        if legacy_face_upserts:
            store.upsert_vectors(IDX_FACES, legacy_face_upserts)

    if object_upserts:
        store.upsert_vectors(IDX_OBJECTS, object_upserts)

    return {
        "uploaded_urls": uploaded_urls,
        "arcface_vecs": len(arcface_upserts),
        "adaface_vecs": len(adaface_upserts),
        "legacy_face_vecs": len(legacy_face_upserts),
        "object_vecs": len(object_upserts),
    }


class UploadService:
    """Service orchestrating image upload, inference, and FAISS vector indexing."""

    def __init__(self, ai=None, ai_semaphore=None, vector_store=None):
        self.ai = ai
        self.sem = ai_semaphore
        self.vector_store = vector_store or faiss_store

    async def upload_and_dispatch_job(
        self,
        *,
        file_bytes_list: List[bytes],
        filenames: List[str],
        folder: str,
        detect_faces: bool,
        user_id: str,
        keys: dict,
        ip: str = "127.0.0.1",
    ) -> dict:
        """
        Decoupled Architecture (Requested by User):
        1. Uploads photos directly to Cloudinary (fast I/O network transfer).
        2. Saves image bytes into local temp directory temp_uploads/{job_id}/.
        3. Enqueues background AI job for face/object embedding & FAISS vector indexing.
        4. Immediately returns HTTP response with job_id, status_url, and Cloudinary URLs in ~1-2s.
        """
        from src.services.jobs import create_job, append_job_log

        start = time.perf_counter()
        folder_std = standardize_category_name(folder)
        job_id = uuid.uuid4().hex

        # Create temporary working directory for this job
        temp_dir = os.path.join("temp_uploads", job_id)
        os.makedirs(temp_dir, exist_ok=True)

        temp_files = []
        for i, (fb, fn) in enumerate(zip(file_bytes_list, filenames)):
            safe_name = f"{i}_{uuid.uuid4().hex[:6]}.jpg"
            temp_path = os.path.join(temp_dir, safe_name)
            with open(temp_path, "wb") as f:
                f.write(fb)
            temp_files.append((fb, temp_path))

        # Parallel Cloudinary Upload (pure I/O)
        cld_tasks = [
            asyncio.to_thread(cld_upload, io.BytesIO(fb), folder_std, keys["cloudinary_creds"])
            for fb, _ in temp_files
        ]
        cld_results = await asyncio.gather(*cld_tasks)
        uploaded_urls = [r.get("secure_url", "") for r in cld_results]

        # Prepare job payload for background AI inference & FAISS indexing
        job_files = [
            {
                "file_id": f"{job_id}_{i}",
                "temp_path": temp_path,
                "url": url,
            }
            for i, ((_, temp_path), url) in enumerate(zip(temp_files, uploaded_urls))
        ]

        job_payload = {
            "files": job_files,
            "folder": folder_std,
            "detect_faces": detect_faces,
            "user_id": user_id or "anonymous",
            "uploaded_urls": uploaded_urls,
            "keys": keys,
        }

        # Enqueue background job
        await create_job(
            job_id=job_id,
            user_id=user_id or "anonymous",
            folder=folder_std,
            total_files=len(file_bytes_list),
            job_payload=job_payload,
        )

        await append_job_log(
            job_id,
            f"All {len(uploaded_urls)} images successfully uploaded to Cloudinary CDN.",
            stage="uploaded",
        )
        await append_job_log(
            job_id,
            "Dispatched background job for deep learning model inference & FAISS vector indexing.",
            stage="queued_for_ai",
        )

        duration_ms = round((time.perf_counter() - start) * 1000)
        log(
            "INFO",
            "upload.dispatched",
            job_id=job_id,
            user_id=user_id,
            files=len(file_bytes_list),
            folder=folder_std,
            upload_duration_ms=duration_ms,
        )

        return {
            "message": "Images uploaded successfully! AI feature extraction and vector indexing job queued.",
            "job_id": job_id,
            "status": "processing",
            "status_url": f"/api/jobs/{job_id}",
            "total_files": len(file_bytes_list),
            "urls": uploaded_urls,
            "user_id": user_id,
        }

    async def process_sync(
        self,
        *,
        file_bytes_list: List[bytes],
        filenames: List[str],
        folder: str,
        detect_faces: bool,
        user_id: str,
        keys: dict,
        ip: str = "127.0.0.1",
    ) -> dict:
        """Process files synchronously: Cloudinary + AI + FAISS upsert (blocking)."""
        start = time.perf_counter()
        folder_std = standardize_category_name(folder)

        results = await asyncio.gather(*[
            process_one_file(
                file_bytes=fb,
                folder=folder_std,
                detect_faces=detect_faces,
                keys=keys,
                ai=self.ai,
                sem=self.sem,
            )
            for fb in file_bytes_list
        ])

        summary = await batch_upsert_all(
            results=results,
            folder=folder_std,
            vector_store=self.vector_store,
        )

        duration_ms = round((time.perf_counter() - start) * 1000)
        log(
            "INFO", "upload.sync_complete",
            user_id=user_id or "anonymous", ip=ip,
            files=len(file_bytes_list), folder=folder_std, duration_ms=duration_ms,
            arcface_vecs=summary["arcface_vecs"],
            adaface_vecs=summary["adaface_vecs"],
            object_vecs=summary["object_vecs"],
        )

        return {
            "message": "Done!",
            "urls": summary["uploaded_urls"],
            "summary": {
                "files": len(file_bytes_list),
                "face_vectors": summary["arcface_vecs"] or summary["legacy_face_vecs"],
                "adaface_vectors": summary["adaface_vecs"],
                "object_vectors": summary["object_vecs"],
                "index_mode": "split" if USE_SPLIT_FACE_INDEXES else "legacy",
            },
        }
