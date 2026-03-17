.PHONY: build test test-python test-integration test-coverage

build:
	bash scripts/build.sh

test: test-python test-integration

test-python:
	python3 -m pytest tests/ -v --ignore=tests/integration

test-integration:
	python3 -m pytest tests/integration/ -v

test-coverage:
	python3 -m pytest tests/ --cov=src/python --cov-report=term-missing --cov-report=html
