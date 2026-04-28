# Dockerfile — Enterprise Lens V3
# InsightFace models download on first run (not at build time)
# This avoids build timeout and network issues during Docker build

FROM python:3.10-slim

WORKDIR /app

# ── System deps ──────────────────────────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgl1 libglib2.0-0 libgomp1 git \
        build-essential cmake g++ \
        wget ca-certificates \
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

# ── Step 4: Remaining requirements ───────────────────────────────
COPY requirements.txt .
RUN pip install --no-cache-dir --prefer-binary -r requirements.txt

# ── Copy app code ─────────────────────────────────────────────────
COPY . .
RUN mkdir -p temp_uploads saved_images && chmod -R 777 temp_uploads saved_images

# ── Hugging Face Auth Token ──────────────────────────────────────
# Define the argument so Docker accepts it during build
ARG HF_TOKEN
# Set it as an environment variable so Python/HuggingFace can see it
ENV HF_TOKEN=$HF_TOKEN

# ── Pre-download ONLY transformers + YOLO at build time ──────────
# InsightFace models download on first startup (cached after that)

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

print("Build complete! InsightFace models download on first startup.")

EOF

EXPOSE 7860
ENV WEB_CONCURRENCY=1


CMD uvicorn main:app \
        --host 0.0.0.0 \
        --port 7860 \

        # Add these environment variables to your existing Dockerfile.
# They significantly improve CPU inference throughput on HF free tier.

ENV OMP_NUM_THREADS=2
ENV MKL_NUM_THREADS=2
ENV OPENBLAS_NUM_THREADS=2
ENV NUMEXPR_NUM_THREADS=2
ENV TOKENIZERS_PARALLELISM=false

# Tell ONNX Runtime to use CPU optimizations aggressively
ENV ORT_DISABLE_ALL_OPTIMIZATIONS=0

# COPY the pre-converted ONNX models into the image.
# Run scripts/convert_to_onnx.py locally first, then commit onnx_models/
# to your Space repo.
COPY onnx_models/ /app/onnx_models/
ENV ONNX_MODELS_DIR=/app/onnx_models


CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "7860"]