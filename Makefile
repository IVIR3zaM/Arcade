.PHONY: test run-cli docker-test

# Quality gate (format, lint, test) via Cairn — see cairn.yaml.
test:
	cairn verify

run-cli:
	python3 -m launcher.cli

# Build the Pi-like Docker image and run the test suite inside it.
docker-test:
	docker build -t arcade-test .
	docker run --rm arcade-test
