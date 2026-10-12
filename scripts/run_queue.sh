# Run eval steps in order, each resumed from the LLM/Jina caches until complete, sleeping through
# Groq's limits (the reported retry-after, or the 00:00 UTC reset of the daily cap).
#   STEPS="v10:lay_dev:--retrieval-only v10:dev:--retrieval-only v10:dev_mini" bash scripts/run_queue.sh
# A step is version:split[:extra evals.run flags, comma-separated]. Needs Docker + the pgvector
# container up. Launch it detached (Start-Process) for multi-day queues: background jobs die with
# the Claude Code session that started them.
cd /e/tax_project
export PYTHONIOENCODING=utf-8
status () {  # "<completed> <total> <retry_after_s> <daily_cap_hit 0/1>"
  .venv/Scripts/python.exe -c "
import io, json, re, sys
try: m = json.load(io.open('results/$1/$2/run_meta.json', encoding='utf-8'))
except Exception: print('0 1 0 0'); sys.exit()
inc = m.get('incomplete') or ''
r = re.search(r'retry after (\d+)', inc)
print(m['n_completed'], m['n_questions'], r.group(1) if r else 0, 1 if 'tokens used today' in inc else 0)"
}
for STEP in $STEPS; do
  IFS=: read -r V S F <<< "$STEP"
  FLAGS=${F//,/ }
  dir=${S//:/_}
  echo "##### $V $S $FLAGS #####"
  for i in $(seq 1 60); do
    .venv/Scripts/python.exe -m evals.run --version "$V" --split "$S" $FLAGS > /dev/null 2>&1
    set -- $(status "$V" "$dir"); n=$1; total=$2; wait_s=$3; daily=$4
    echo "[$V $S #$i] $n/$total backoff=${wait_s}s daily_cap=$daily  $(date -u "+%m-%d %H:%M")UTC"
    [ "$n" -ge "$total" ] && { echo "[$V $S] COMPLETE"; break; }
    if [ "$daily" = 1 ]; then
      now=$(date -u +%s); next=$(date -u -d "tomorrow 00:05" +%s); nap=$((next-now))
      echo "[$V $S] daily cap reached; sleeping ${nap}s until the 00:00 UTC reset"
    else
      nap=$((wait_s+120)); [ "$nap" -lt 180 ] && nap=180
    fi
    sleep "$nap"
  done
done
echo "##### queue done $(date -u) #####"
