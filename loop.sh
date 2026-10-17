#!/bin/bash
# Runs watch.py every INTERVAL seconds for LOOP_SECONDS. State is committed right after a change.
# Logs contain only counts/status (watch.py prints no addresses or criteria).
INTERVAL=${INTERVAL:-120}
LOOP_SECONDS=${LOOP_SECONDS:-19800}   # 5.5 h
git config user.name "github-actions[bot]"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"

sync() {  # fetch latest (pending.json from the box) and replay local unpushed commits
  for i in 1 2 3; do git pull -q --rebase --autostash origin main 2>/dev/null && return 0; git rebase --abort 2>/dev/null; sleep 2; done
  echo "warn: pull failed"; return 1
}
commit_push() {
  git add state
  git diff --cached --quiet && return 0
  git commit -q -m "state update"
  for i in 1 2 3 4 5; do
    git push -q origin HEAD:main 2>/dev/null && { echo "state committed"; return 0; }
    echo "push conflict, retry $i"; sleep $((i*2)); sync
  done
  echo "warn: push failed, retry next iteration"
}

# keepalive against GitHub's 60-day schedule disable
sync
if [ $(( $(date +%s) - $(git log -1 --format=%ct) )) -gt $((25*86400)) ]; then
  date -u +%Y-%m-%d > state/keepalive.txt; commit_push
fi

end=$((SECONDS + LOOP_SECONDS)); n=0
while [ $SECONDS -lt $end ]; do
  t0=$SECONDS; n=$((n+1))
  sync
  printf 'iter %d %s ' "$n" "$(date -u +%H:%M:%SZ)"
  timeout 100 python3 watch.py --state-dir state || echo "warn: watch.py exit $?"
  commit_push
  left=$(( INTERVAL - (SECONDS - t0) )); [ $left -gt 0 ] && [ $((SECONDS + left)) -lt $end ] && sleep $left
done
echo "loop done after $n iterations"
