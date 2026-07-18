from __future__ import annotations

import unittest
from pathlib import Path

from invoice_auditor.json_parser import ModelOutputError
from invoice_auditor.models import ModelTrace, RawInvoiceData
from invoice_auditor.runtime import RuntimeInfo
from invoice_auditor.vlm_runtime import ModelProfile, ModelRegistry, VLMRuntime
from tests.helpers import valid_raw

PRIMARY_SHA = "a" * 40
FALLBACK_SHA = "b" * 40


def _registry() -> ModelRegistry:
    return ModelRegistry(
        schema_version="1.0.0",
        acceptance_status="candidate_unverified",
        primary=ModelProfile(
            model_id="primary",
            revision=PRIMARY_SHA,
            min_free_vram_mb=12000,
        ),
        fallback=ModelProfile(
            model_id="fallback",
            revision=FALLBACK_SHA,
            min_free_vram_mb=9000,
        ),
    )


def _runtime(free_vram_mb: float = 16000) -> RuntimeInfo:
    return RuntimeInfo(
        python_version="3.12",
        platform="test",
        executable="python",
        colab=True,
        packages={"torch": "2.8.0"},
        cuda_available=True,
        cuda_version="12.6",
        gpu_name="test-gpu",
        compute_capability="8.0",
        total_vram_mb=16000,
        free_vram_mb=free_vram_mb,
        disk_free_mb=100000,
    )


def _trace(model_id: str, revision: str) -> ModelTrace:
    return ModelTrace(
        model_id=model_id,
        model_revision=revision,
        prompt_version="test",
        generation_parameters={},
        latency_ms=1,
    )


class _FakeExtractor:
    def __init__(self, profile: ModelProfile, *, load_error=None, extract_error=None) -> None:
        self.profile = profile
        self.load_error = load_error
        self.extract_error = extract_error
        self.released = False

    def load(self) -> None:
        if self.load_error:
            raise self.load_error

    def extract(self, image_path: str | Path) -> tuple[RawInvoiceData, ModelTrace]:
        if self.extract_error:
            raise self.extract_error
        return RawInvoiceData.model_validate(valid_raw()), _trace(
            self.profile.model_id, self.profile.revision
        )

    def release(self) -> None:
        self.released = True


class VLMRuntimeTests(unittest.TestCase):
    def test_packaged_and_repository_registries_are_identical(self) -> None:
        root = Path(__file__).resolve().parents[1]
        repository = (root / "config/models.colab.json").read_text(encoding="utf-8")
        packaged = (root / "src/invoice_auditor/resources/models.colab.json").read_text(
            encoding="utf-8"
        )
        self.assertEqual(repository, packaged)

    def test_preflight_selects_fallback_and_records_reason(self) -> None:
        created: list[str] = []

        def factory(profile: ModelProfile) -> _FakeExtractor:
            created.append(profile.model_id)
            return _FakeExtractor(profile)

        runtime = VLMRuntime(
            _registry(), runtime_info=_runtime(10000), extractor_factory=factory
        )
        _, trace = runtime.extract("unused.png")
        self.assertEqual(created, ["fallback"])
        self.assertEqual(trace.fallback_from, "primary")
        self.assertIn("preflight_vram", trace.fallback_reason or "")

    def test_allowlisted_oom_during_load_falls_back(self) -> None:
        created: list[str] = []

        def factory(profile: ModelProfile) -> _FakeExtractor:
            created.append(profile.model_id)
            error = RuntimeError("CUDA out of memory") if profile.model_id == "primary" else None
            return _FakeExtractor(profile, load_error=error)

        runtime = VLMRuntime(_registry(), runtime_info=_runtime(), extractor_factory=factory)
        _, trace = runtime.extract("unused.png")
        self.assertEqual(created, ["primary", "fallback"])
        self.assertEqual(trace.fallback_from, "primary")
        self.assertIn("cuda_oom", trace.fallback_reason or "")

    def test_parse_failure_does_not_trigger_fallback(self) -> None:
        created: list[str] = []

        def factory(profile: ModelProfile) -> _FakeExtractor:
            created.append(profile.model_id)
            return _FakeExtractor(profile, extract_error=ModelOutputError("invalid JSON"))

        runtime = VLMRuntime(_registry(), runtime_info=_runtime(), extractor_factory=factory)
        with self.assertRaises(ModelOutputError):
            runtime.extract("unused.png")
        self.assertEqual(created, ["primary"])

    def test_generic_inference_failure_does_not_trigger_fallback(self) -> None:
        created: list[str] = []

        def factory(profile: ModelProfile) -> _FakeExtractor:
            created.append(profile.model_id)
            return _FakeExtractor(profile, extract_error=RuntimeError("bad operator input"))

        runtime = VLMRuntime(_registry(), runtime_info=_runtime(), extractor_factory=factory)
        with self.assertRaises(RuntimeError):
            runtime.extract("unused.png")
        self.assertEqual(created, ["primary"])


if __name__ == "__main__":
    unittest.main()
