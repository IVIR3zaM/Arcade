# PlayStation 1 BIOS (you supply this)

DuckStation needs a PS1 BIOS to boot games. The BIOS is **copyrighted**, so it is
never baked into the image and never committed to this repo — you drop your own
copy here and `make docker-play` mounts this directory (read-only) into
DuckStation's BIOS folder inside the container.

Put your BIOS file(s) in this directory, e.g.:

```
bios/ps1/scph5501.bin
```

Everything in here except this README is git-ignored, so your BIOS stays local.

Point `make docker-play` at a different location with `PS1_BIOS_DIR`:

```bash
make docker-play PS1_BIOS_DIR=/path/to/your/ps1/bios
```
