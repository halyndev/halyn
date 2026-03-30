.PHONY: install dev test lint type-check serve scan clean docker

install:
	pip install -e .

dev:
	pip install -e ".[dev]"

test:
	PYTHONPATH=src python -m pytest tests/ -v --tb=short

test-fast:
	PYTHONPATH=src python tests/test_halyn.py

lint:
	ruff check src/ tests/

type-check:
	mypy src/halyn/ --ignore-missing-imports

serve:
	PYTHONPATH=src python -m halyn serve

scan:
	PYTHONPATH=src python -m halyn scan

docker:
	docker build -t halyn .

docker-up:
	docker compose up -d

docker-down:
	docker compose down

clean:
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -name '*.pyc' -delete
	rm -rf build/ dist/ *.egg-info .mypy_cache .ruff_cache .pytest_cache
