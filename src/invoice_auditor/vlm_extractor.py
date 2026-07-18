"""Optional Qwen/Transformers adapter with production-oriented telemetry."""

from __future__ import annotations

from contextlib import nullcontext
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Any

from invoice_auditor.json_parser import parse_model_json
from invoice_auditor.models import ModelTrace, RawInvoiceData
from invoice_auditor.preprocessing import load_safe_document
from invoice_auditor.runtime import package_version

PROMPT_VERSION = "invoice-extraction-v1"
EXTRACTION_PROMPT = """You are a document extraction component, not an auditor.
Read the invoice image and return exactly one JSON object with these keys:
invoice_number, vendor_name, tax_id, invoice_date, subtotal, vat, total, currency.
Use null when a value is missing, unreadable, or unsupported. Never infer a missing value from
arithmetic and never add keys. Preserve visible number/date text as strings. Return JSON only."""


@dataclass(frozen=True, slots=True)
class ExtractorSettings:
    model_id: str = "Qwen/Qwen3-VL-4B-Instruct"
    model_revision: str | None = None
    runtime_profile: str = "standard"
    dtype: str = "auto"
    quantization: str | None = None
    max_new_tokens: int = 512
    longest_side: int = 1600
    local_files_only: bool = True

    def __post_init__(self) -> None:
        if not self.model_id or len(self.model_id) > 256:
            raise ValueError("model_id must be between 1 and 256 characters")
        if not 64 <= self.max_new_tokens <= 2048:
            raise ValueError("max_new_tokens must be between 64 and 2048")
        if self.dtype not in {"auto", "float16", "bfloat16"}:
            raise ValueError("dtype must be auto, float16, or bfloat16")
        if self.quantization not in {None, "4bit"}:
            raise ValueError("quantization must be null or 4bit")


class QwenVLMExtractor:
    """Lazily loaded extractor. One instance is designed for repeated image inference."""

    def __init__(self, settings: ExtractorSettings | None = None) -> None:
        self.settings = settings or ExtractorSettings()
        self._model: Any = None
        self._processor: Any = None
        self._torch: Any = None
        self._model_load_ms: int | None = None

    @property
    def is_loaded(self) -> bool:
        return self._model is not None and self._processor is not None

    def load(self) -> None:
        if self.is_loaded:
            return
        try:
            import torch
            from transformers import AutoModelForMultimodalLM, AutoProcessor
        except ImportError as exc:
            raise RuntimeError(
                "VLM dependencies are missing; install requirements-colab.lock or .[vlm]"
            ) from exc

        started = perf_counter()
        common: dict[str, Any] = {"local_files_only": self.settings.local_files_only}
        if self.settings.model_revision:
            common["revision"] = self.settings.model_revision
        model_kwargs: dict[str, Any] = {
            "device_map": "auto",
            "dtype": self._resolve_dtype(torch),
            **common,
        }
        if self.settings.quantization == "4bit":
            try:
                from transformers import BitsAndBytesConfig
            except ImportError as exc:
                raise RuntimeError(
                    "4bit profile requires transformers BitsAndBytes support"
                ) from exc
            model_kwargs["quantization_config"] = BitsAndBytesConfig(
                load_in_4bit=True,
                bnb_4bit_quant_type="nf4",
                bnb_4bit_compute_dtype=torch.bfloat16,
            )

        processor = AutoProcessor.from_pretrained(self.settings.model_id, **common)
        model = AutoModelForMultimodalLM.from_pretrained(
            self.settings.model_id,
            **model_kwargs,
        )
        model.eval()
        self._torch = torch
        self._processor = processor
        self._model = model
        self._model_load_ms = round((perf_counter() - started) * 1000)

    def _resolve_dtype(self, torch: Any) -> Any:
        if self.settings.dtype == "auto":
            return "auto"
        return getattr(torch, self.settings.dtype)

    def _cuda_ready(self) -> bool:
        try:
            return bool(self._torch is not None and self._torch.cuda.is_available())
        except (AttributeError, RuntimeError):
            return False

    def _synchronize(self) -> None:
        if self._cuda_ready():
            self._torch.cuda.synchronize()

    def extract(self, image_path: str | Path) -> tuple[RawInvoiceData, ModelTrace]:
        self.load()
        total_started = perf_counter()

        preprocess_started = perf_counter()
        image = load_safe_document(image_path, longest_side=self.settings.longest_side)
        preprocess_ms = round((perf_counter() - preprocess_started) * 1000)
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "image", "image": image},
                    {"type": "text", "text": EXTRACTION_PROMPT},
                ],
            }
        ]

        if self._cuda_ready():
            self._torch.cuda.reset_peak_memory_stats()
        self._synchronize()
        inference_started = perf_counter()
        inputs = self._processor.apply_chat_template(
            messages,
            tokenize=True,
            add_generation_prompt=True,
            return_dict=True,
            return_tensors="pt",
        )
        inputs = inputs.to(self._model.device)
        context = self._torch.inference_mode() if self._torch is not None else nullcontext()
        with context:
            generated = self._model.generate(
                **inputs,
                max_new_tokens=self.settings.max_new_tokens,
                do_sample=False,
            )
        self._synchronize()
        inference_ms = round((perf_counter() - inference_started) * 1000)
        trimmed = [
            output[len(input_ids) :]
            for input_ids, output in zip(inputs.input_ids, generated, strict=True)
        ]
        response = self._processor.batch_decode(
            trimmed,
            skip_special_tokens=True,
            clean_up_tokenization_spaces=False,
        )[0].strip()
        raw = RawInvoiceData.model_validate(parse_model_json(response))
        peak_vram_mb = None
        if self._cuda_ready():
            peak_vram_mb = round(self._torch.cuda.max_memory_allocated() / (1024**2), 2)

        trace = ModelTrace(
            model_id=self.settings.model_id,
            model_revision=self.settings.model_revision,
            prompt_version=PROMPT_VERSION,
            runtime_profile=self.settings.runtime_profile,
            device=str(getattr(self._model, "device", "unknown")),
            dtype=str(getattr(self._model, "dtype", self.settings.dtype)),
            quantization=self.settings.quantization,
            torch_version=package_version("torch"),
            transformers_version=package_version("transformers"),
            cuda_version=getattr(getattr(self._torch, "version", None), "cuda", None),
            gpu_name=(str(self._torch.cuda.get_device_name(0)) if self._cuda_ready() else None),
            model_load_ms=self._model_load_ms,
            preprocess_ms=preprocess_ms,
            inference_ms=inference_ms,
            generation_parameters={
                "max_new_tokens": self.settings.max_new_tokens,
                "do_sample": False,
                "longest_side": self.settings.longest_side,
                "local_files_only": self.settings.local_files_only,
            },
            latency_ms=round((perf_counter() - total_started) * 1000),
            peak_vram_mb=peak_vram_mb,
            raw_response=response,
        )
        return raw, trace

    def release(self) -> None:
        self._model = None
        self._processor = None
        import gc

        gc.collect()
        if self._cuda_ready():
            self._torch.cuda.empty_cache()
