"""
One-time ONNX conversion + dynamic INT8 quantization.

Run locally:
    python scripts/convert_to_onnx.py

Produces:
    onnx_models/siglip_vision_int8.onnx
    onnx_models/dinov2_int8.onnx

Fix: attn_implementation="eager" disables scaled_dot_product_attention,
which the legacy PyTorch ONNX exporter cannot trace (TypeError on Sqrt/scale).
"""
import os
import torch
import torch.nn as nn
from pathlib import Path
from onnxruntime.quantization import quantize_dynamic, QuantType

OUT_DIR = Path("onnx_models")
OUT_DIR.mkdir(exist_ok=True)


def export_siglip():
    print("Exporting SigLIP vision encoder...")
    from transformers import SiglipVisionModel

    model = SiglipVisionModel.from_pretrained(
        "google/siglip-base-patch16-224",
        attn_implementation="eager",  # disables SDPA — required for ONNX export
    ).eval()

    class SigLIPWrapper(nn.Module):
        def __init__(self, m):
            super().__init__()
            self.m = m

        def forward(self, pixel_values):
            return self.m(pixel_values=pixel_values).pooler_output

    wrapper = SigLIPWrapper(model).eval()
    dummy = torch.randn(1, 3, 224, 224)

    with torch.no_grad():
        test = wrapper(dummy)
    print(f"  Forward pass OK — output shape: {test.shape}")

    fp32_path = OUT_DIR / "siglip_vision.onnx"
    with torch.no_grad():
        torch.onnx.export(
            wrapper, dummy, fp32_path,
            input_names=["pixel_values"],
            output_names=["image_embeds"],
            dynamic_axes={"pixel_values": {0: "batch"}, "image_embeds": {0: "batch"}},
            opset_version=14,
            do_constant_folding=True,
        )
    print(f"  fp32 saved ({fp32_path.stat().st_size // 1024 // 1024} MB)")

    int8_path = OUT_DIR / "siglip_vision_int8.onnx"
    quantize_dynamic(str(fp32_path), str(int8_path), weight_type=QuantType.QInt8)
    print(f"  INT8 saved ({int8_path.stat().st_size // 1024 // 1024} MB)")
    os.remove(fp32_path)


def export_dinov2():
    print("\nExporting DINOv2...")
    from transformers import AutoModel

    model = AutoModel.from_pretrained(
        "facebook/dinov2-base",
        attn_implementation="eager",  # same fix
    ).eval()

    class DINOv2Wrapper(nn.Module):
        def __init__(self, m):
            super().__init__()
            self.m = m

        def forward(self, pixel_values):
            return self.m(pixel_values=pixel_values).last_hidden_state[:, 0, :]

    wrapper = DINOv2Wrapper(model).eval()
    dummy = torch.randn(1, 3, 224, 224)

    with torch.no_grad():
        test = wrapper(dummy)
    print(f"  Forward pass OK — output shape: {test.shape}")

    fp32_path = OUT_DIR / "dinov2.onnx"
    with torch.no_grad():
        torch.onnx.export(
            wrapper, dummy, fp32_path,
            input_names=["pixel_values"],
            output_names=["cls_features"],
            dynamic_axes={"pixel_values": {0: "batch"}, "cls_features": {0: "batch"}},
            opset_version=14,
            do_constant_folding=True,
        )
    print(f"  fp32 saved ({fp32_path.stat().st_size // 1024 // 1024} MB)")

    int8_path = OUT_DIR / "dinov2_int8.onnx"
    quantize_dynamic(str(fp32_path), str(int8_path), weight_type=QuantType.QInt8)
    print(f"  INT8 saved ({int8_path.stat().st_size // 1024 // 1024} MB)")
    os.remove(fp32_path)


if __name__ == "__main__":
    print(f"PyTorch {torch.__version__}")
    export_siglip()
    export_dinov2()
    print("\nDone. Commit onnx_models/*.onnx to your Space repo.")
    for f in sorted(OUT_DIR.glob("*.onnx")):
        print(f"  {f.name}  ({f.stat().st_size // 1024 // 1024} MB)")