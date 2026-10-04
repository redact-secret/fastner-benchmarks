PY ?= python3

.PHONY: test validate
test:
	$(PY) -m unittest discover -s tests

validate: test
	$(PY) -m fnbench policy-check
	$(PY) -m fnbench populations-check
	$(PY) -m fnbench pins-check
	$(PY) -m fnbench report --check
