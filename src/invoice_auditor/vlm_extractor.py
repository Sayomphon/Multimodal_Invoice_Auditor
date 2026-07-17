"""Optional local Qwen/Transformers adapter kept outside the deterministic core."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Any

from invoice_auditor.json_parser import parse_model_json
from invoice_auditor.models import ModelTrace, RawInvoiceData
from invoice_auditor.preprocessing import load_safe_image

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
    max_new_tokens: int = 512
    longest_side: int = 1600
    local_files_only: bool = True

    def __post_init__(self) -> None:
        if not self.model_id or len(self.model_id) > 256:
            raise ValueError("model_id must be between 1 and 256 characters")
        if not 64 <= self.max_new_tokens <= 2048:
            raise ValueError("max_new_tokens must be between 64 and 2048")


class QwenVLMExtractor:
    """Lazily loaded local extractor. No model/network access occurs at import time."""

    def __init__(self, settings: ExtractorSettings | None = None) -> None:
        self.settings = settings or ExtractorSettings()
        self._model: Any = None
        self._processor: Any = None

    def _load(self) -> None:
        if self._model is not None:
            return
        try:
            from transformers import AutoModelForMultimodalLM, AutoProcessor
        except ImportError as exc:
            raise RuntimeError(
                "VLM dependencies are missing; install with: pip install -e '.[vlm]'"
            ) from exc

        common: dict[str, Any] = {
            "local_files_only": self.settings.local_files_only,
        }
        if self.settings.model_revision:
            common["revision"] = self.settings.model_revision
        self._processor = AutoProcessor.from_pretrained(self.settings.model_id, **common)
        self._model = AutoModelForMultimodalLM.from_pretrained(
            self.settings.model_id,
            dtype="auto",
            device_map="auto",
            **common,
        )
        self._model.eval()

    def extract(self, image_path: str | Path) -> tuple[RawInvoiceData, ModelTrace]:
        self._load()
        image = load_safe_image(image_path, longest_side=self.settings.longest_side)
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "image", "image": image},
                    {"type": "text", "text": EXTRACTION_PROMPT},
                ],
            }
        ]
        started = perf_counter()
        inputs = self._processor.apply_chat_template(
            messages,
            tokenize=True,
            add_generation_prompt=True,
            return_dict=True,
            return_tensors="pt",
        )
        inputs = inputs.to(self._model.device)
        generated = self._model.generate(
            **inputs,
            max_new_tokens=self.settings.max_new_tokens,
            do_sample=False,
        )
        trimmed = [
            output[len(input_ids) :]
            for input_ids, output in zip(inputs.input_ids, generated, strict=True)
        ]
        response = self._processor.batch_decode(
            trimmed,
            skip_special_tokens=True,
            clean_up_tokenization_spaces=False,
        )[0].strip()
        latency_ms = round((perf_counter() - started) * 1000)
        raw = RawInvoiceData.model_validate(parse_model_json(response))
        trace = ModelTrace(
            model_id=self.settings.model_id,
            model_revision=self.settings.model_revision,
            prompt_version=PROMPT_VERSION,
            generation_parameters={
                "max_new_tokens": self.settings.max_new_tokens,
                "do_sample": False,
                "longest_side": self.settings.longest_side,
                "local_files_only": self.settings.local_files_only,
            },
            latency_ms=latency_ms,
            raw_response=response,
        )
        return raw, trace

