# watch

Periodically checks a public listing overview and sends a webhook when something relevant changes.

- `watch.py` — fetch, parse, diff against `state/`, dispatch.
- Config via repository secrets: `MATCH_CONFIG` (JSON), `HEF_WEBHOOK_URL`, `HEF_WEBHOOK_KEY`.
- Runs via GitHub Actions: each job loops `loop.sh` (check every ~2 min for ~5.5 h); a schedule keeps a follow-up run queued.
