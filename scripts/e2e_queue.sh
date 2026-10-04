# Run dev_mini end-to-end for each version in turn, resuming from the answer cache and sleeping
# the provider's reported retry-after between passes. Usage: VERSIONS="v3 v4 v5" bash scripts/e2e_queue.sh
# Needs Docker + the pgvector container up. Expect hours of wall clock when Groq is throttling.
cd /e/tax_project
export PYTHONIOENCODING=utf-8
status () {  # "<completed> <retry_after_s> <daily_cap_hit 0/1>"
  .venv/Scripts/python.exe -c "
import io, json, re, sys
try: m = json.load(io.open('results/$1/dev_mini/run_meta.json', encoding='utf-8'))
except Exception: print('0 0 0'); sys.exit()
inc = m.get('incomplete') or ''
r = re.search(r'retry after (\d+)', inc)
print(m['n_completed'], r.group(1) if r else 0, 1 if 'tokens used today' in inc else 0)"
}
for V in ${VERSIONS:-v3 v4 v5}; do
  echo "##### $V #####"
  for i in $(seq 1 40); do
    .venv/Scripts/python.exe -m evals.run --version "$V" --split dev_mini > /dev/null 2>&1
    set -- $(status "$V"); n=$1; wait_s=$2; daily=$3
    echo "[$V #$i] $n/30 backoff=${wait_s}s daily_cap=$daily  $(date -u +%H:%M)UTC"
    [ "$n" -ge 30 ] && { echo "[$V] COMPLETE"; break; }
    if [ "$daily" = 1 ]; then
      now=$(date -u +%s); next=$(date -u -d "tomorrow 00:05" +%s); nap=$((next-now))
      echo "[$V] daily cap reached; sleeping ${nap}s until the 00:00 UTC reset"
    else
      nap=$((wait_s+120)); [ "$nap" -lt 180 ] && nap=180
    fi
    sleep "$nap"
  done
done
echo "##### done #####"; for V in ${VERSIONS:-v3 v4 v5}; do echo "$V: $(status $V)"; done
