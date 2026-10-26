#!/bin/bash
# Encrypts/decrypts the watcher state. Only state/<name>.json.enc is committed; plaintext state/*.json is gitignored.
# Key comes from env STATE_KEY (Actions secret) or file STATE_KEY_FILE; never passed on a command line.
#   state_crypt.sh decrypt DIR   -> DIR/*.json.enc => DIR/*.json   (fails, touching nothing, on bad key/corrupt data)
#   state_crypt.sh encrypt DIR   -> re-encrypt DIR/*.json only if it differs from the decrypted committed .enc
#   state_crypt.sh check         -> exit 1 if no key is configured
set -u
FILES="hef_state.json dispatch_state.json hef_pending.json"
if [ -n "${STATE_KEY_FILE:-}" ]; then PASS="file:$STATE_KEY_FILE"; else PASS="env:STATE_KEY"; fi
die() { echo "STATE_CRYPT ERROR: $*" >&2; exit 1; }
[ -n "${STATE_KEY_FILE:-}" ] && [ ! -s "$STATE_KEY_FILE" ] && die "key file missing or empty"
[ -z "${STATE_KEY_FILE:-}" ] && [ -z "${STATE_KEY:-}" ] && die "STATE_KEY not set (repo secret missing?)"
OPTS="-aes-256-cbc -pbkdf2 -iter 200000 -md sha256 -salt"

dec() {  # dec ENC OUT : decrypt + validate JSON, write OUT atomically
  local tmp="$2.dec.tmp"
  if ! openssl enc -d $OPTS -pass "$PASS" -in "$1" -out "$tmp" 2>/dev/null \
     || ! python3 -c 'import json,sys; json.load(open(sys.argv[1]))' "$tmp" 2>/dev/null; then
    rm -f "$tmp"; return 1
  fi
  mv -f "$tmp" "$2"
}

cmd=${1:-}; dir=${2:-state}
case "$cmd" in
  check) exit 0 ;;
  decrypt)
    for f in $FILES; do
      [ -f "$dir/$f.enc" ] || { [ "$f" = hef_state.json ] && die "$dir/$f.enc missing, refusing to start with empty state"; continue; }
      dec "$dir/$f.enc" "$dir/$f" || die "cannot decrypt $dir/$f.enc (wrong STATE_KEY or corrupt file); state left untouched"
    done ;;
  encrypt)
    n=0
    for f in $FILES; do
      p="$dir/$f"; e="$p.enc"
      [ -f "$p" ] || continue
      python3 -c 'import json,sys; json.load(open(sys.argv[1]))' "$p" 2>/dev/null || die "$p is not valid JSON; not encrypting"
      if [ -f "$e" ]; then
        old="$p.old.tmp"
        dec "$e" "$old" || { rm -f "$old"; die "cannot decrypt existing $e; refusing to overwrite it"; }
        if cmp -s "$old" "$p"; then rm -f "$old"; continue; fi
        rm -f "$old"
      fi
      openssl enc -e $OPTS -pass "$PASS" -in "$p" -out "$e.tmp" 2>/dev/null || { rm -f "$e.tmp"; die "encrypt of $p failed"; }
      mv -f "$e.tmp" "$e"; n=$((n+1))
    done
    [ $n -gt 0 ] && echo "encrypted $n file(s)" ;;
  *) die "usage: state_crypt.sh check|decrypt DIR|encrypt DIR" ;;
esac
exit 0
