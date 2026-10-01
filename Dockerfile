# Dockerfile — Enterprise Lens V3
# Model weights are downloaded BEFORE copying code so that
# code changes use Docker layer cache and never re-download models.

FROM python:3.10-slim

WORKDIR /app

# ── System deps ──────────────────────────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgl1 libglib2.0-0 libgomp1 git \
        build-essential cmake g++ \
        wget curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# ── Step 1: Build tools (MUST be before insightface) ─────────────
RUN pip install --no-cache-dir \
        "numpy<2.0" \
        "setuptools>=65" \
        wheel \
        cython \
        scikit-build \
        cmake

# ── Step 2: onnxruntime (MUST be before insightface) ─────────────
RUN pip install --no-cache-dir onnxruntime

# ── Step 3: insightface ───────────────────────────────────────────
RUN pip install --no-cache-dir --prefer-binary "insightface>=0.7.3"

# ── Step 4: Python dependencies ───────────────────────────────────
COPY requirements.txt .
RUN pip install --no-cache-dir --prefer-binary -r requirements.txt

# ── Step 5: Hugging Face Auth Token & Pre-download AI Models ─────
# MUST BE BEFORE "COPY . ." so code edits don't invalidate model cache
ARG HF_TOKEN
ENV HF_TOKEN=$HF_TOKEN

RUN python - <<'EOF'
import os
os.environ["TRANSFORMERS_VERBOSITY"] = "error"

print("Pre-downloading SigLIP...")
from transformers import AutoProcessor, AutoModel
AutoProcessor.from_pretrained("google/siglip-base-patch16-224", use_fast=True)
AutoModel.from_pretrained("google/siglip-base-patch16-224")
print("SigLIP done")

print("Pre-downloading DINOv2...")
from transformers import AutoImageProcessor
AutoImageProcessor.from_pretrained("facebook/dinov2-base")
AutoModel.from_pretrained("facebook/dinov2-base")
print("DINOv2 done")

print("Pre-downloading YOLO seg...")
from ultralytics import YOLO
YOLO("yolo11n-seg.pt")
print("YOLO done")

print("Pre-downloading InsightFace models...")
try:
    from insightface.app import FaceAnalysis
    app = FaceAnalysis(name="buffalo_l", providers=["CPUExecutionProvider"])
    app.prepare(ctx_id=-1, det_size=(640, 640))
    print("InsightFace done")
except Exception as e:
    print(f"InsightFace download skipped at build time ({e}), will download on startup.")

print("All heavy models pre-downloaded and cached successfully!")
EOF

# ── Step 6: Environment variables & CPU optimization ──────────────
ENV WEB_CONCURRENCY=1 \
    OMP_NUM_THREADS=2 \
    MKL_NUM_THREADS=2 \
    OPENBLAS_NUM_THREADS=2 \
    NUMEXPR_NUM_THREADS=2 \
    TOKENIZERS_PARALLELISM=false \
    ORT_DISABLE_ALL_OPTIMIZATIONS=0 \
    ONNX_MODELS_DIR=/app/onnx_models

# ── Step 7: Pre-converted ONNX models (if present) ─────────────────
COPY onnx_models/ /app/onnx_models/

# ── Step 8: Copy app code (PLACED LAST FOR INSTANT CODE REBUILDS) ─
# Any edit to main.py, src/, etc. starts build from here in ~1 sec
COPY . .
RUN mkdir -p temp_uploads saved_images && chmod -R 777 temp_uploads saved_images

EXPOSE 7860

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "7860", "--reload"]