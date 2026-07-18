"""CPU-safe runtime detection and environment telemetry for Colab/local runs."""

from __future__ import annotations

import importlib.metadata
import os
import platform
import shutil
import sys
from pathlib import Path
from typing import Any

from pydantic import Field

from invoice_auditor.io_utils import atomic_write_json
from invoice_auditor.models import StrictModel

PACKAGE_NAMES = ("torch", "transformers", "accelerate", "safetensors", "pypdfium2")


class RuntimeInfo(StrictModel):
    """Serializable runtime facts; unavailable accelerator values remain null."""

    python_version: str
    platform: str
    executable: str
    colab: bool
    packages: dict[str, str | None]
    cuda_available: bool
    cuda_version: str | None = None
    gpu_name: str | None = None
    compute_capability: str | None = None
    total_vram_mb: float | None = Field(default=None, ge=0)
    free_vram_mb: float | None = Field(default=None, ge=0)
    disk_free_mb: float = Field(ge=0)


def package_version(name: str) -> str | None:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def _torch_runtime(torch_module: Any | None = None) -> dict[str, Any]:
    torch = torch_module
    if torch is None:
        try:
            import torch as imported_torch
        except ImportError:
            return {"cuda_available": False}
        torch = imported_torch

    try:
        available = bool(torch.cuda.is_available())
    except (AttributeError, RuntimeError):
        available = False
    if not available:
        return {
            "cuda_available": False,
            "cuda_version": getattr(getattr(torch, "version", None), "cuda", None),
        }

    result: dict[str, Any] = {
        "cuda_available": True,
        "cuda_version": getattr(getattr(torch, "version", None), "cuda", None),
    }
    try:
        result["gpu_name"] = str(torch.cuda.get_device_name(0))
        major, minor = torch.cuda.get_device_capability(0)
        result["compute_capability"] = f"{major}.{minor}"
        free_bytes, total_bytes = torch.cuda.mem_get_info(0)
        result["free_vram_mb"] = round(free_bytes / (1024**2), 2)
        result["total_vram_mb"] = round(total_bytes / (1024**2), 2)
    except (AttributeError, RuntimeError, TypeError, ValueError):
        # CUDA may disappear between availability detection and device queries.
        result["cuda_available"] = False
    return result


def detect_runtime(
    *,
    disk_path: str | Path = ".",
    torch_module: Any | None = None,
) -> RuntimeInfo:
    disk_root = Path(disk_path).expanduser().resolve()
    disk_free_mb = round(shutil.disk_usage(disk_root).free / (1024**2), 2)
    accelerator = _torch_runtime(torch_module)
    packages = {name: package_version(name) for name in PACKAGE_NAMES}
    if torch_module is not None and packages["torch"] is None:
        packages["torch"] = getattr(torch_module, "__version__", None)
    return RuntimeInfo(
        python_version=platform.python_version(),
        platform=platform.platform(),
        executable=sys.executable,
        colab="google.colab" in sys.modules or bool(os.environ.get("COLAB_RELEASE_TAG")),
        packages=packages,
        disk_free_mb=disk_free_mb,
        **accelerator,
    )


def write_environment(
    path: str | Path,
    *,
    disk_path: str | Path = ".",
    torch_module: Any | None = None,
) -> Path:
    runtime = detect_runtime(disk_path=disk_path, torch_module=torch_module)
    return atomic_write_json(path, runtime.model_dump(mode="json"))
