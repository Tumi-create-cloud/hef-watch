# watch

Periodically checks a public listing overview and sends a webhook when something relevant changes.

- `watch.py` — fetch, parse, diff against `state/`, dispatch.
- Config via repository secrets: `MATCH_CONFIG` (JSON), `HEF_WEBHOOK_URL`, `HEF_WEBHOOK_KEY`.
- Runs on a schedule via GitHub Actions (`.github/workflows/watch.yml`).
