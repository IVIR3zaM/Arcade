.PHONY: test run-cli docker-test docker-play

# Quality gate (format, lint, test) via Cairn — see cairn.yaml.
test:
	cairn verify

run-cli:
	python3 -m launcher.cli

# Build the Pi-like Docker image and run the test suite inside it.
docker-test:
	docker build -t arcade-test .
	docker run --rm arcade-test

# Build the real-emulator image and run it with a VNC desktop you can view from
# the Mac host: connect a VNC viewer to localhost:5900 to watch RetroArch.
docker-play:
	docker build -f Dockerfile.play -t arcade-play .
	docker run --rm -it -p 5900:5900 arcade-play
