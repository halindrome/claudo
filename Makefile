.PHONY: build test test-python test-coverage

build:
	bash scripts/build.sh

test: test-python

test-python:
	python3 -m pytest tests/ -v

test-coverage:
	python3 -m pytest tests/ --cov=src/python --cov-report=term-missing --cov-report=html
