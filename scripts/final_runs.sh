#!/usr/bin/env bash
# Phase 11: the final numbers on the frozen test split (84 questions), queued so Groq's free tier
# can carry them over several days. Every run resumes from the answer cache, so re-running this
# script after an interruption only spends tokens on what is missing.
#   bash scripts/final_runs.sh                 # needs Docker + the db container up
#
# Cost estimates (gpt-oss-120b, 195K/day budget in configs/models.yaml):
#   v6, v8 retrieval-only   0 (scope check on gpt-oss-20b, ~35K once; v8 reuses v6's cache)
#   v8 end to end         ~175K   the shipped version
#   oracle end to end      ~70K   the ceiling
#   v2 end to end         ~170K   structural chunking, the first big step
#   v5 end to end         ~200K   best retrieval-only version before the agent
#   v0 end to end         ~380K   the naive baseline (512-token windows fill the budget)
cd "$(dirname "$0")/.."
export PYTHONIOENCODING=utf-8
PY=.venv/Scripts/python.exe
[ -x "$PY" ] || PY=.venv/bin/python

status () {  # "<completed> <n> <retry_after_s> <daily_cap_hit 0/1>"
  "$PY" -c "
import io, json, re, sys
try: m = json.load(io.open('results/$1/test/run_meta.json', encoding='utf-8'))
except Exception: print('0 1 0 0'); sys.exit()
inc = m.get('incomplete') or ''
r = re.search(r'retry after (\d+)', inc)
print(m['n_completed'], m['n_questions'], r.group(1) if r else 0, 1 if 'tokens used today' in inc else 0)"
}

run_until_done () {  # version, extra args...
  local V=$1; shift
  echo "##### $V $* #####"
  for i in $(seq 1 60); do
    "$PY" -m evals.run --version "$V" --split test --final "$@" > /dev/null 2>&1
    read -r n total wait_s daily <<< "$(status "$V")"
    echo "[$V #$i] $n/$total backoff=${wait_s}s daily_cap=$daily  $(date -u +%H:%M)UTC"
    if [ "$n" -ge "$total" ] && [ "$wait_s" = 0 ] && [ "$daily" = 0 ]; then
      echo "[$V] COMPLETE"; return 0
    fi
    if [ "$daily" = 1 ]; then
      now=$(date -u +%s); next=$(date -u -d "tomorrow 00:05" +%s); nap=$((next-now))
      echo "[$V] daily cap reached; sleeping ${nap}s until the 00:00 UTC reset"
    else
      nap=$((wait_s+120)); [ "$nap" -lt 180 ] && nap=180
    fi
    sleep "$nap"
  done
  echo "[$V] gave up after 60 passes"
}

run_until_done v6 --retrieval-only
run_until_done v8 --retrieval-only
run_until_done v8
run_until_done oracle
run_until_done v2
run_until_done v5
run_until_done v0
echo "##### done #####"
"$PY" -m evals.report --split test
