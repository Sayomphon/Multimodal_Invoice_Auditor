"""Optional loopback-only Gradio surface for portfolio demonstrations."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from invoice_auditor.config import RuleConfig, default_rule_config
from invoice_auditor.pipeline import InvoiceAuditPipeline
from invoice_auditor.vlm_extractor import ExtractorSettings, QwenVLMExtractor


def create_demo(
    *,
    model_id: str,
    model_revision: str | None = None,
    allow_download: bool = False,
    config: RuleConfig | None = None,
) -> Any:
    try:
        import gradio as gr
    except ImportError as exc:
        raise RuntimeError(
            "demo dependencies are missing; install with: pip install -e '.[vlm,demo]'"
        ) from exc

    pipeline = InvoiceAuditPipeline(config or default_rule_config())
    extractor = QwenVLMExtractor(
        ExtractorSettings(
            model_id=model_id,
            model_revision=model_revision,
            local_files_only=not allow_download,
        )
    )

    def audit_image(
        image_path: str | None,
    ) -> tuple[
        str,
        dict[str, Any],
        dict[str, Any],
        list[dict[str, Any]],
    ]:
        if not image_path:
            return "ERROR", {}, {}, [{"message": "กรุณาเลือกไฟล์ภาพ"}]
        try:
            raw, trace = extractor.extract(Path(image_path))
            report = pipeline.audit(raw, source_id=Path(image_path).name, model_trace=trace)
            return (
                report.decision.value,
                report.raw.model_dump(mode="json"),
                report.normalized.model_dump(mode="json"),
                [rule.model_dump(mode="json") for rule in report.rules],
            )
        except Exception as exc:  # Gradio boundary returns a safe operator-visible error.
            return "ERROR", {}, {}, [{"message": str(exc)}]

    with gr.Blocks(title="Multimodal Invoice Auditor") as app:
        gr.Markdown(
            "# Multimodal Invoice Auditor\n"
            "VLM ใช้สำหรับ extraction เท่านั้น "
            "ส่วนการคำนวณและ decision เป็น deterministic rules"
        )
        with gr.Row():
            image = gr.Image(type="filepath", label="Invoice image")
            with gr.Column():
                decision = gr.Textbox(label="Decision", interactive=False)
                raw = gr.JSON(label="Raw extraction")
                normalized = gr.JSON(label="Normalized invoice")
        rules = gr.JSON(label="Rule results")
        run_button = gr.Button("Audit", variant="primary")
        run_button.click(
            audit_image,
            inputs=[image],
            outputs=[decision, raw, normalized, rules],
        )
    return app


def launch_demo(
    *,
    model_id: str,
    model_revision: str | None = None,
    allow_download: bool = False,
    port: int = 7860,
    config: RuleConfig | None = None,
) -> None:
    if not 1024 <= port <= 65535:
        raise ValueError("port must be between 1024 and 65535")
    app = create_demo(
        model_id=model_id,
        model_revision=model_revision,
        allow_download=allow_download,
        config=config,
    )
    app.launch(
        server_name="127.0.0.1",
        server_port=port,
        share=False,
        show_error=False,
        max_file_size="20mb",
    )
