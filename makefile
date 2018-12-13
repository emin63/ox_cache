
.PHONY: pypi help

help:
	@echo "This is a makefile to push to pypi."
	@echo "Use 'make test' to run tests"
	@echo "Use 'make pypi' to push to pypi."

pypi: README.rst
	 python3 setup.py sdist upload -r pypi

test:
	py.test --cov=. --cov-report term-missing \
          -vvv --doctest-modules --doctest-glob='*.md' .

README.rst: README.md
	pandoc --from=markdown --to=rst --output=README.rst README.md

