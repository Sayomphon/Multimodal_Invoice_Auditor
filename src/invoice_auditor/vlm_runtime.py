"""Strict model registry plus allowlisted primary/fallback orchestration."""

from __future__ import annotations

from collections.abc import Callable
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Literal, Protocol

from pydantic import Field, StringConstraints, ValidationError

from invoice_auditor.io_utils import load_json_object
from invoice_auditor.json_parser import ModelOutputError
from invoice_auditor.models import ModelTrace, RawInvoiceData, StrictModel
from invoice_auditor.preprocessing import UnsafeDocumentError
from invoice_auditor.runtime import RuntimeInfo, detect_runtime
from invoice_auditor.vlm_extractor import ExtractorSettings, QwenVLMExtractor

RevisionSha = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{40}$")]


class ErrorStage(StrEnum):
    PREFLIGHT = "preflight"
    MODEL_LOAD = "model_load"
    PREPROCESS = "preprocess"
    INFERENCE = "inference"
    PARSE = "parse"
    SCHEMA = "schema"
    AUDIT = "audit"


class ModelProfile(StrictModel):
    model_id: str = Field(min_length=1, max_length=256)
    revision: RevisionSha
    profile: Literal["standard", "4bit"] = "standard"
    dtype: Literal["auto", "float16", "bfloat16"] = "auto"
    min_free_vram_mb: int = Field(default=0, ge=0)


class ModelRegistry(StrictModel):
    schema_version: Literal["1.0.0"]
    acceptance_status: Literal["candidate_unverified", "colab_verified"]
    primary: ModelProfile
    fallback: ModelProfile


class ErrorClassification(StrictModel):
    stage: ErrorStage
    error_type: str
    message: str
    fallback_eligible: bool = False


class VLMRuntimeError(RuntimeError):
    def __init__(self, classification: ErrorClassification) -> None:
        super().__init__(classification.message)
        self.classification = classification


class Extractor(Protocol):
    def load(self) -> None: ...

    def extract(self, image_path: str | Path) -> tuple[RawInvoiceData, ModelTrace]: ...

    def release(self) -> None: ...


_OOM_MARKERS = (
    "cuda out of memory",
    "cublas_status_alloc_failed",
    "hip out of memory",
    "outofmemoryerror",
)
_COMPATIBILITY_MARKERS = (
    "qwen3_vl",
    "qwen2_5_vl",
    "unrecognized configuration class",
    "does not recognize this architecture",
    "requires transformers",
    "no module named 'bitsandbytes'",
    "operator torchvision::nms does not exist",
)


def classify_error(exc: BaseException, stage: ErrorStage | None = None) -> ErrorClassification:
    if isinstance(exc, VLMRuntimeError):
        return exc.classification
    if isinstance(exc, UnsafeDocumentError):
        resolved_stage = ErrorStage.PREPROCESS
    elif isinstance(exc, ModelOutputError):
        resolved_stage = ErrorStage.PARSE
    elif isinstance(exc, ValidationError):
        resolved_stage = ErrorStage.SCHEMA
    else:
        resolved_stage = stage or ErrorStage.INFERENCE
    message = str(exc).strip() or exc.__class__.__name__
    normalized = f"{exc.__class__.__name__}: {message}".casefold()
    eligible = resolved_stage in {ErrorStage.MODEL_LOAD, ErrorStage.INFERENCE} and (
        any(marker in normalized for marker in _OOM_MARKERS)
        or any(marker in normalized for marker in _COMPATIBILITY_MARKERS)
    )
    if any(marker in normalized for marker in _COMPATIBILITY_MARKERS):
        error_type = "compatibility_error"
    elif any(marker in normalized for marker in _OOM_MARKERS):
        error_type = "cuda_oom"
    else:
        error_type = exc.__class__.__name__
    return ErrorClassification(
        stage=resolved_stage,
        error_type=error_type,
        message=message[:1000],
        fallback_eligible=eligible,
    )


def load_model_registry(path: str | Path) -> ModelRegistry:
    return ModelRegistry.model_validate(load_json_object(path, max_bytes=64 * 1024))


class VLMRuntime:
    """Load once, reuse across images, and only fallback for allowlisted failures."""

    def __init__(
        self,
        registry: ModelRegistry,
        *,
        allow_download: bool = False,
        max_new_tokens: int = 512,
        longest_side: int = 1600,
        require_cuda: bool = True,
        runtime_info: RuntimeInfo | None = None,
        extractor_factory: Callable[[ModelProfile], Extractor] | None = None,
    ) -> None:
        self.registry = registry
        self.allow_download = allow_download
        self.max_new_tokens = max_new_tokens
        self.longest_side = longest_side
        self.require_cuda = require_cuda
        self.runtime_info = runtime_info or detect_runtime()
        self._extractor_factory = extractor_factory or self._default_factory
        self._extractor: Extractor | None = None
        self._active_profile: ModelProfile | None = None
        self._fallback_from: str | None = None
        self._fallback_reason: str | None = None

    @property
    def active_profile(self) -> ModelProfile | None:
        return self._active_profile

    def _default_factory(self, profile: ModelProfile) -> Extractor:
        return QwenVLMExtractor(
            ExtractorSettings(
                model_id=profile.model_id,
                model_revision=profile.revision,
                runtime_profile=profile.profile,
                dtype=profile.dtype,
                quantization="4bit" if profile.profile == "4bit" else None,
                max_new_tokens=self.max_new_tokens,
                longest_side=self.longest_side,
                local_files_only=not self.allow_download,
            )
        )

    def _preflight_profile(self) -> tuple[ModelProfile, str | None]:
        if self.require_cuda and not self.runtime_info.cuda_available:
            classification = ErrorClassification(
                stage=ErrorStage.PREFLIGHT,
                error_type="cuda_unavailable",
                message="CUDA GPU is required by the Colab VLM runtime profile",
            )
            raise VLMRuntimeError(classification)
        free = self.runtime_info.free_vram_mb
        primary = self.registry.primary
        fallback = self.registry.fallback
        if free is not None and free < primary.min_free_vram_mb:
            reason = (
                f"preflight_vram: free={free:.0f}MB < primary_required="
                f"{primary.min_free_vram_mb}MB"
            )
            if free < fallback.min_free_vram_mb:
                raise VLMRuntimeError(
                    ErrorClassification(
                        stage=ErrorStage.PREFLIGHT,
                        error_type="insufficient_vram",
                        message=f"{reason}; fallback_required={fallback.min_free_vram_mb}MB",
                    )
                )
            return fallback, reason
        return primary, None

    def _activate(self, profile: ModelProfile) -> None:
        extractor = self._extractor_factory(profile)
        try:
            extractor.load()
        except Exception as exc:
            classification = classify_error(exc, ErrorStage.MODEL_LOAD)
            try:
                extractor.release()
            finally:
                if not classification.fallback_eligible or profile == self.registry.fallback:
                    raise VLMRuntimeError(classification) from exc
            self._fallback_from = profile.model_id
            self._fallback_reason = f"{classification.error_type}: {classification.message}"
            fallback = self._extractor_factory(self.registry.fallback)
            try:
                fallback.load()
            except Exception as fallback_exc:
                failure = classify_error(fallback_exc, ErrorStage.MODEL_LOAD)
                fallback.release()
                raise VLMRuntimeError(failure) from fallback_exc
            self._extractor = fallback
            self._active_profile = self.registry.fallback
            return
        self._extractor = extractor
        self._active_profile = profile

    def load(self) -> None:
        if self._extractor is not None:
            return
        profile, preflight_reason = self._preflight_profile()
        if preflight_reason:
            self._fallback_from = self.registry.primary.model_id
            self._fallback_reason = preflight_reason
        self._activate(profile)

    def extract(self, image_path: str | Path) -> tuple[RawInvoiceData, ModelTrace]:
        self.load()
        assert self._extractor is not None
        assert self._active_profile is not None
        try:
            raw, trace = self._extractor.extract(image_path)
        except Exception as exc:
            classification = classify_error(exc)
            if (
                not classification.fallback_eligible
                or self._active_profile == self.registry.fallback
            ):
                raise
            failed_model = self._active_profile.model_id
            self._extractor.release()
            self._fallback_from = failed_model
            self._fallback_reason = f"{classification.error_type}: {classification.message}"
            self._extractor = None
            self._active_profile = None
            self._activate(self.registry.fallback)
            assert self._extractor is not None
            raw, trace = self._extractor.extract(image_path)
        trace = trace.model_copy(
            update={
                "fallback_from": self._fallback_from,
                "fallback_reason": self._fallback_reason,
            }
        )
        return raw, trace

    def release(self) -> None:
        if self._extractor is not None:
            self._extractor.release()
        self._extractor = None
        self._active_profile = None


def default_registry_path() -> Path:
    repository_registry = Path(__file__).resolve().parents[2] / "config" / "models.colab.json"
    if repository_registry.is_file():
        return repository_registry
    return Path(__file__).resolve().parent / "resources" / "models.colab.json"
