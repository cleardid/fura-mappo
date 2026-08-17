SHELL := /bin/bash

.PHONY: install test lint format audit smoke clean

install:
	python -m pip install -e ".[dev]"

test:
	python -m pytest -q

lint:
	python -m ruff check .

format:
	python -m ruff format .
	python -m ruff check --fix .

audit:
	bash scripts/collect_system_info.sh

smoke:
	bash scripts/smoke_test.sh

clean:
	rm -rf .pytest_cache .ruff_cache build dist *.egg-info src/*.egg-info
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
