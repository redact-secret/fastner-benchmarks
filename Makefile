PY ?= python3

.PHONY: test validate
test:
	$(PY) -m unittest discover -s tests -v

validate: test
	$(PY) -m fnbench policy-check
