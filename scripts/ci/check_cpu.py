"""Check installed CI CPU runtimes, not scientific artifact admission."""
from importlib import metadata

import onnxruntime
import torch
import torchvision


def main():
    assert torch.__version__ == "2.15.0+cpu"
    assert torchvision.__version__ == "0.29.2+cpu"
    assert torch.version.cuda is None
    assert "CPUExecutionProvider" in onnxruntime.get_available_providers()
    assert not any(p in onnxruntime.get_available_providers() for p in ("CUDAExecutionProvider", "TensorrtExecutionProvider"))
    assert not any(d.metadata["Name"].lower().startswith(("nvidia-", "cuda-", "triton")) for d in metadata.distributions())
    print("Pinned PyTorch/Torchvision CPU and ONNX Runtime installed; no CUDA distributions.")


if __name__ == "__main__":
    main()
