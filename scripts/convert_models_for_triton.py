"""
scripts/convert_models_for_triton.py
Phase 3: Model Export and TensorRT Staging Pipeline for NVIDIA Triton.

Converts PyTorch & ONNX vision models into standardized Triton model repository
artifacts with dynamic batch axes for high-throughput continuous batching.
"""
import os
import shutil
import subprocess
from pathlib import Path
import torch
import torch.nn as nn

REPO_ROOT = Path(__file__).resolve().parent.parent
MODEL_REPO = REPO_ROOT / "model_repository"
ONNX_MODELS_DIR = REPO_ROOT / "onnx_models"


def export_siglip(output_dir: Path):
    """
    Exports Google SigLIP (768D Vision Transformer) to ONNX with dynamic batch size.
    Input:  pixel_values: [batch, 3, 224, 224] (FP32)
    Output: last_hidden_state: [batch, 768] (FP32)
    """
    print("[1/6] Exporting SigLIP Vision Encoder...")
    target_dir = output_dir / "siglip_embedder" / "1"
    target_dir.mkdir(parents=True, exist_ok=True)
    onnx_file = target_dir / "model.onnx"

    # Fast-path: check if pre-existing converted ONNX exists in onnx_models/
    prebuilt = ONNX_MODELS_DIR / "siglip_vision_int8.onnx"
    if prebuilt.exists() and not onnx_file.exists():
        shutil.copy2(prebuilt, onnx_file)
        print(f"  ✓ Staged pre-built SigLIP from {prebuilt} ({onnx_file.stat().st_size // 1024 // 1024} MB)")
        return

    try:
        from transformers import SiglipVisionModel

        # eager attention is required so PyTorch ONNX tracer can trace attention heads
        model = SiglipVisionModel.from_pretrained(
            "google/siglip-base-patch16-224",
            attn_implementation="eager"
        ).eval()

        class SiglipWrapper(nn.Module):
            def __init__(self, core):
                super().__init__()
                self.core = core

            def forward(self, pixel_values):
                return self.core(pixel_values=pixel_values).pooler_output

        wrapper = SiglipWrapper(model).eval()
        dummy_input = torch.randn(1, 3, 224, 224)

        with torch.no_grad():
            torch.onnx.export(
                wrapper,
                dummy_input,
                str(onnx_file),
                input_names=["pixel_values"],
                output_names=["last_hidden_state"],
                dynamic_axes={
                    "pixel_values": {0: "batch_size"},
                    "last_hidden_state": {0: "batch_size"}
                },
                opset_version=14,
                do_constant_folding=True,
            )
        print(f"  ✓ Exported SigLIP to {onnx_file} ({onnx_file.stat().st_size // 1024 // 1024} MB)")
    except Exception as e:
        print(f"  ⚠ SigLIP export encountered error: {e}")


def export_dinov2(output_dir: Path):
    """
    Exports Meta DINOv2-base (768D Vision Transformer) to ONNX with dynamic batch size.
    Input:  pixel_values: [batch, 3, 224, 224] (FP32)
    Output: last_hidden_state: [batch, 768] (CLS token)
    """
    print("\n[2/6] Exporting DINOv2 Base...")
    target_dir = output_dir / "dinov2_embedder" / "1"
    target_dir.mkdir(parents=True, exist_ok=True)
    onnx_file = target_dir / "model.onnx"

    # Fast-path: check if pre-existing converted ONNX exists in onnx_models/
    prebuilt = ONNX_MODELS_DIR / "dinov2_int8.onnx"
    if prebuilt.exists() and not onnx_file.exists():
        shutil.copy2(prebuilt, onnx_file)
        print(f"  ✓ Staged pre-built DINOv2 from {prebuilt} ({onnx_file.stat().st_size // 1024 // 1024} MB)")
        return

    try:
        from transformers import AutoModel

        model = AutoModel.from_pretrained(
            "facebook/dinov2-base",
            attn_implementation="eager"
        ).eval()

        class DINOv2Wrapper(nn.Module):
            def __init__(self, core):
                super().__init__()
                self.core = core

            def forward(self, pixel_values):
                # Extract CLS token from index 0 of the sequence
                return self.core(pixel_values=pixel_values).last_hidden_state[:, 0, :]

        wrapper = DINOv2Wrapper(model).eval()
        dummy_input = torch.randn(1, 3, 224, 224)

        with torch.no_grad():
            torch.onnx.export(
                wrapper,
                dummy_input,
                str(onnx_file),
                input_names=["pixel_values"],
                output_names=["last_hidden_state"],
                dynamic_axes={
                    "pixel_values": {0: "batch_size"},
                    "last_hidden_state": {0: "batch_size"}
                },
                opset_version=14,
                do_constant_folding=True,
            )
        print(f"  ✓ Exported DINOv2 to {onnx_file} ({onnx_file.stat().st_size // 1024 // 1024} MB)")
    except Exception as e:
        print(f"  ⚠ DINOv2 export encountered error: {e}")


def export_adaface(output_dir: Path):
    """
    Exports AdaFace iResNet-50 (512D) to ONNX with dynamic batch size.
    Input:  input_0: [batch, 3, 112, 112] (FP32 normalized face chips)
    Output: output_0: [batch, 512] (L2 face feature vectors)
    """
    print("\n[3/6] Exporting AdaFace Recognizer...")
    target_dir = output_dir / "adaface_recognizer" / "1"
    target_dir.mkdir(parents=True, exist_ok=True)
    onnx_file = target_dir / "model.onnx"

    try:
        from src.services.ai_manager import AIModelManager
        mgr = AIModelManager()
        if mgr.adaface_model is None:
            print("  ⚠ AdaFace not loaded in AIModelManager, skipping ONNX export.")
            return

        model = mgr.adaface_model.eval()
        dummy_input = torch.randn(1, 3, 112, 112)

        with torch.no_grad():
            torch.onnx.export(
                model,
                dummy_input,
                str(onnx_file),
                input_names=["input_0"],
                output_names=["output_0"],
                dynamic_axes={
                    "input_0": {0: "batch_size"},
                    "output_0": {0: "batch_size"}
                },
                opset_version=14,
                do_constant_folding=True,
            )
        print(f"  ✓ Exported AdaFace to {onnx_file} ({onnx_file.stat().st_size // 1024 // 1024} MB)")
    except Exception as e:
        print(f"  ⚠ AdaFace export skipped ({e})")


def stage_insightface_models(output_dir: Path):
    """
    Extracts & stages SCRFD Face Detector (det_10g.onnx) and ArcFace Face Recognizer (w600k_r50.onnx)
    from InsightFace's buffalo_l bundle into Triton layout.
    """
    print("\n[4/6] Staging InsightFace (SCRFD Detector & ArcFace Recognizer)...")
    try:
        from insightface.app import FaceAnalysis
        app = FaceAnalysis(name="buffalo_l", providers=["CPUExecutionProvider"])
        app.prepare(ctx_id=-1, det_size=(640, 640))

        # Check standard cache location for buffalo_l
        buffalo_dir = Path.home() / ".insightface" / "models" / "buffalo_l"
        if not buffalo_dir.exists():
            print(f"  ⚠ buffalo_l directory not found at {buffalo_dir}")
            return

        # 1. SCRFD Face Detector
        scrfd_src = buffalo_dir / "det_10g.onnx"
        if scrfd_src.exists():
            scrfd_target = output_dir / "scrfd_detector" / "1"
            scrfd_target.mkdir(parents=True, exist_ok=True)
            shutil.copy2(scrfd_src, scrfd_target / "model.onnx")
            print(f"  ✓ Staged SCRFD Detector to {scrfd_target / 'model.onnx'}")

        # 2. ArcFace Face Recognizer
        arcface_src = buffalo_dir / "w600k_r50.onnx"
        if arcface_src.exists():
            arcface_target = output_dir / "arcface_recognizer" / "1"
            arcface_target.mkdir(parents=True, exist_ok=True)
            shutil.copy2(arcface_src, arcface_target / "model.onnx")
            print(f"  ✓ Staged ArcFace Recognizer to {arcface_target / 'model.onnx'}")

    except Exception as e:
        print(f"  ⚠ InsightFace staging skipped ({e})")


def export_yolo(output_dir: Path):
    """
    Exports YOLO11 segmentation to ONNX format with dynamic batch.
    """
    print("\n[5/6] Exporting YOLO11 Segmenter...")
    target_dir = output_dir / "yolo11_segmenter" / "1"
    target_dir.mkdir(parents=True, exist_ok=True)

    try:
        from ultralytics import YOLO
        yolo = YOLO("yolo11n-seg.pt")
        export_path = yolo.export(format="onnx", dynamic=True, opset=14)
        dest = target_dir / "model.onnx"
        if os.path.exists(export_path):
            os.replace(export_path, dest)
            print(f"  ✓ Exported YOLO11 to {dest}")
    except Exception as e:
        print(f"  ⚠ YOLO export skipped ({e})")


def compile_tensorrt_engine(onnx_path: Path, plan_path: Path, input_shape: str):
    """
    Compiles an ONNX model into a TensorRT FP16 execution plan using trtexec.
    Only executed on machines with an NVIDIA GPU and TensorRT installed.
    """
    if not onnx_path.exists():
        print(f"  ⚠ Source ONNX file {onnx_path} does not exist.")
        return

    cmd = [
        "trtexec",
        f"--onnx={onnx_path}",
        f"--saveEngine={plan_path}",
        "--fp16",
        f"--minShapes={input_shape.format(batch=1)}",
        f"--optShapes={input_shape.format(batch=8)}",
        f"--maxShapes={input_shape.format(batch=32)}",
    ]
    print(f"Compiling TensorRT: {' '.join(cmd)}")
    subprocess.run(cmd, check=True)
    print(f"  ✓ Successfully compiled TensorRT engine: {plan_path}")


def stage_all():
    MODEL_REPO.mkdir(exist_ok=True)
    print(f"== Starting Model Export and Staging to {MODEL_REPO} ==")
    export_siglip(MODEL_REPO)
    export_dinov2(MODEL_REPO)
    export_adaface(MODEL_REPO)
    stage_insightface_models(MODEL_REPO)
    export_yolo(MODEL_REPO)
    print("\n== Model Export Pipeline Finished ==")


if __name__ == "__main__":
    stage_all()