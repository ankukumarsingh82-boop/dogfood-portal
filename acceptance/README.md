# Acceptance suite

`run.py` is the official Dogfood checker (stdlib only). This repo claims T1 in `.dogfood.toml`.

With the portal up from `docker compose up --build`:

```bash
python3 acceptance/run.py .dogfood.toml > acceptance-report.txt
```

`run.py` looks for `fixtures.json` in the working directory, beside itself, and beside `.dogfood.toml`. The repo root file is a link to `fixtures/fixtures.json`, which is also what Compose seeds. `example.dogfood.toml` is the upstream template. The claim this portal actually makes is `.dogfood.toml`.

The checker does not log in. It sends the cookies in `[auth]`. T1 expects a public gallery at `/e/evt_01/gallery` that contains fixture project titles, and a participant POST to `/e/evt_01/submission` that returns 4xx because Sample Hack closed on 2026-03-01.

T2 requests (judge scores, peer isolation, CSV export) are part of the same script. Those routes are not implemented, so they fail. That is the honest result. Do not flip `claimed` to include T2 until those checks pass.

`acceptance-report.txt` is the output of that command, not a hand-written summary.
