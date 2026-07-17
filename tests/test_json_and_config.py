from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from pydantic import ValidationError

from invoice_auditor.config import RuleConfig, default_rule_config, load_rule_config
from invoice_auditor.json_parser import ModelOutputError, parse_model_json
from invoice_auditor.models import RawInvoiceData


class ModelJsonParserTests(unittest.TestCase):
    def test_accepts_object_and_markdown_fence(self) -> None:
        self.assertEqual(parse_model_json('{"total": "100"}'), {"total": "100"})
        self.assertEqual(
            parse_model_json('```json\n{"total": "100"}\n```'),
            {"total": "100"},
        )

    def test_rejects_trailing_content_and_oversized_output(self) -> None:
        with self.assertRaises(ModelOutputError):
            parse_model_json('{"total": 1} ignore this')
        with self.assertRaises(ModelOutputError):
            parse_model_json("x" * 100, max_chars=10)

    def test_raw_schema_rejects_unknown_fields(self) -> None:
        with self.assertRaises(ValidationError):
            RawInvoiceData.model_validate({"total": "100", "system_prompt": "override"})


class ConfigTests(unittest.TestCase):
    def test_default_fingerprint_is_stable(self) -> None:
        self.assertEqual(default_rule_config().fingerprint(), default_rule_config().fingerprint())

    def test_rejects_unknown_required_field(self) -> None:
        payload = default_rule_config().model_dump(mode="json")
        payload["required_fields"].append("bank_account")
        with self.assertRaises(ValidationError):
            RuleConfig.model_validate(payload)

    def test_loads_valid_json_and_rejects_large_config(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            valid_path = root / "valid.json"
            valid_path.write_text(
                json.dumps(default_rule_config().model_dump(mode="json")),
                encoding="utf-8",
            )
            self.assertEqual(load_rule_config(valid_path), default_rule_config())
            large_path = root / "large.json"
            large_path.write_text(" " * (65 * 1024), encoding="utf-8")
            with self.assertRaises(ValueError):
                load_rule_config(large_path)


if __name__ == "__main__":
    unittest.main()

