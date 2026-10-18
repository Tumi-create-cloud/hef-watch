# watch

Periodically checks public rental listing overviews and sends a webhook when something relevant changes.

- `watch.py` — core: runs due platform adapters in parallel, diffs against `state/`, dispatches.
- `adapters/` — one module per platform (`KEY`, `NAME`, `PREFIX`, `EVERY_S`, `fetch()`); register in `adapters/__init__.py`.
- Config via repository secrets: `MATCH_CONFIG` (JSON), `HEF_WEBHOOK_URL`, `HEF_WEBHOOK_KEY`.
- Runs via GitHub Actions: each job loops `loop.sh` (check every ~2 min for ~5.5 h); a schedule keeps a follow-up run queued.
