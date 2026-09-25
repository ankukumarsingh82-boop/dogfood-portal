# Acceptance suite

The official Dogfood acceptance suite was not in this repository at build time. Drop it in this directory when it is published and run it against the portal from `docker compose up`.

This repo does not ship a fabricated `acceptance-report.txt`. Tier claims live in `.dogfood.toml` and are limited to T1.

Our own tests, which are not a substitute for the official suite, are in `tests/` and run with:

```bash
pip install -r requirements-dev.txt
pytest
```
