# Local stand-in for the Raspberry Pi: a Debian + Python image that mirrors the
# Pi's Linux userland. This is a dev/test tool only (see ITERATIONS.md, Phase 0)
# — it is NOT part of what ships on the Pi.
FROM python:3.12-slim-bookworm

WORKDIR /app

# Install dependencies first so this layer is cached across source changes.
COPY requirements.txt requirements-dev.txt ./
RUN pip install --no-cache-dir -r requirements.txt -r requirements-dev.txt

# Copy the application source.
COPY . .

# Default: run the test suite inside the container.
CMD ["python", "-m", "pytest"]
