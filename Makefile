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

# Where you drop the PlayStation BIOS (e.g. scph5501.bin). It's copyrighted, so it
# is NEVER baked into the image or committed — you supply it here and we mount it.
PS1_BIOS_DIR ?= $(CURDIR)/bios/ps1

# Build the real-emulator image and run it with a VNC desktop you can view from
# the Mac host: connect a VNC viewer to localhost:5900 to watch RetroArch.
# The PS1 BIOS dir is mounted read-only into DuckStation's bios folder.
docker-play:
	docker build -f Dockerfile.play -t arcade-play .
	mkdir -p $(PS1_BIOS_DIR)
	docker run --rm -it -p 5900:5900 \
		-v $(PS1_BIOS_DIR):/root/.local/share/duckstation/bios:ro \
		arcade-play
