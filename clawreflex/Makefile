PYTHON ?= python3

.PHONY: test lint types coverage security browser build doctor bench

test:
	$(PYTHON) -m unittest discover -s clawreflex -p 'test_*.py'

lint:
	ruff check clawreflex

types:
	mypy

coverage:
	coverage run -m unittest discover -s clawreflex -p 'test_*.py'
	coverage report --fail-under=85

security:
	$(PYTHON) -m unittest clawreflex.tests.test_security clawreflex.tests.test_apply clawreflex.tests.test_http

browser:
	node --test clawreflex/openclaw/test_plugin.mjs clawreflex/openclaw/test_monitor.mjs

build:
	$(PYTHON) -m build

doctor:
	$(PYTHON) -m clawreflex.doctor

bench:
	clawreflex-bench --help
