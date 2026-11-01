.PHONY: test security build site
test:      ## run all tests (needs git; no installs)
	python -m unittest discover -s tests -t .
security:  ## attack tests + static scan (pip install bandit)
	python -m unittest tests.test_security && bandit -r footnote -q --severity-level low
build:     ## one-file installer + checksum (reproducible)
	python build_pyz.py dist
site:      ## preview the website at http://localhost:8000
	python -m http.server 8000 --directory site
