#!/bin/bash
# Box only: decrypt the latest committed watcher state (origin/main) to a directory outside the repo.
# Usage: tools/decrypt_state.sh [OUT_DIR]   (default /workspace/woning/watcher_state)
set -eu
REPO=$(cd "$(dirname "$0")/.." && pwd)
OUT=${1:-/workspace/woning/watcher_state}
export STATE_KEY_FILE=${STATE_KEY_FILE:-/home/box/.secrets/hef_watch_state_key}
git -C "$REPO" fetch -q origin main
TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT
for f in hef_state.json dispatch_state.json hef_pending.json; do
  git -C "$REPO" show "origin/main:state/$f.enc" > "$TMP/$f.enc" 2>/dev/null || rm -f "$TMP/$f.enc"
done
"$REPO/tools/state_crypt.sh" decrypt "$TMP"
mkdir -p "$OUT"; chmod 700 "$OUT"
for f in "$TMP"/*.json; do cp "$f" "$OUT/"; done
git -C "$REPO" log -1 --format='%H %cI' origin/main > "$OUT/.source_commit"
echo "decrypted to $OUT ($(ls "$TMP"/*.json | wc -l) files, commit $(git -C "$REPO" rev-parse --short origin/main))"
