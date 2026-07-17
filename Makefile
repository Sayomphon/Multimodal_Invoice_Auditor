.PHONY: install test lint smoke

install:
	python -m pip install -e ".[dev]"

test:
	python -m pytest

lint:
	ruff check src tests

smoke:
	invoice-auditor audit-json tests/fixtures/pass_invoice.json --public-output

