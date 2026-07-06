.PHONY: test run-cli

# Quality gate (format, lint, test) via Cairn — see cairn.yaml.
test:
	cairn verify

run-cli:
	python3 -m launcher.cli
