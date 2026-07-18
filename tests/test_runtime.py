from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from invoice_auditor.runtime import detect_runtime


class _CpuCuda:
    @staticmethod
    def is_available() -> bool:
        return False


class _GpuCuda:
    @staticmethod
    def is_available() -> bool:
        return True

    @staticmethod
    def get_device_name(index: int) -> str:
        return f"Fake GPU {index}"

    @staticmethod
    def get_device_capability(index: int) -> tuple[int, int]:
        return (8, index)

    @staticmethod
    def mem_get_info(index: int) -> tuple[int, int]:
        gib = 1024**3
        return (10 * gib, 16 * gib)


class RuntimeDetectionTests(unittest.TestCase):
    def test_cpu_detection_does_not_require_torch_install(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fake = SimpleNamespace(cuda=_CpuCuda(), version=SimpleNamespace(cuda=None))
            result = detect_runtime(disk_path=temporary, torch_module=fake)
            self.assertFalse(result.cuda_available)
            self.assertIsNone(result.gpu_name)
            self.assertGreater(result.disk_free_mb, 0)

    def test_gpu_telemetry_uses_nullable_runtime_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fake = SimpleNamespace(
                cuda=_GpuCuda(),
                version=SimpleNamespace(cuda="12.6"),
                __version__="2.8.0",
            )
            result = detect_runtime(disk_path=Path(temporary), torch_module=fake)
            self.assertTrue(result.cuda_available)
            self.assertEqual(result.gpu_name, "Fake GPU 0")
            self.assertEqual(result.compute_capability, "8.0")
            self.assertEqual(result.free_vram_mb, 10240.0)


if __name__ == "__main__":
    unittest.main()
