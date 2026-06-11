.PHONY: test lint fmt predict edges clv

test:
	uv run pytest

lint:
	uv run ruff check src tests
	uv run ruff format --check src tests
	uv run mypy

fmt:
	uv run ruff check --fix src tests
	uv run ruff format src tests

predict:
	uv run wc26 predict

edges:
	uv run wc26 edges

clv:
	uv run wc26 clv-report
