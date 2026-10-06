import { useEffect, useState } from 'react'
import type { EvalRow } from '../api'
import { getEvals } from '../api'
import { ColumnChart } from './ColumnChart'

const SHIPPED = 'v6'
const pct = (v: number | undefined) => (v == null ? '—' : v.toFixed(3))
const int = (v: number | undefined) => (v == null ? '—' : Math.round(v).toLocaleString())

export function LadderView() {
  const [mini, setMini] = useState<EvalRow[] | null>(null)
  const [dev, setDev] = useState<EvalRow[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    Promise.all([getEvals('dev_mini'), getEvals('dev')])
      .then(([a, b]) => { setMini(a.versions); setDev(b.versions) })
      .catch(() => setError('The results could not be loaded. Start the API with: python -m statnav.api'))
  }, [])

  if (error) return <div className="ladder"><p className="error" role="alert">{error}</p></div>
  if (!mini || !dev) return <div className="ladder"><p className="hint">Loading the results…</p></div>

  const versions = mini.filter((r) => r.version !== 'oracle')
  const oracle = mini.find((r) => r.version === 'oracle')
  const recall = new Map(dev.map((r) => [r.version, r.metrics['recall@5']]))

  return (
    <div className="ladder">
      <h2 className="ladder-title">How each change to the pipeline moved the scores</h2>
      <p className="ladder-lede">
        Every version adds one change to the one before it and is scored on the same questions:
        30 end-to-end (6 each of lookups, rate tables, amendments, multi-step questions and
        out-of-scope questions) and 138 for retrieval. One question moves a per-type score by 0.17,
        so read small end-to-end differences as noise. Version {SHIPPED} answers in this app.
      </p>

      <div className="charts">
        <ColumnChart
          title="Facts found in the answer"
          subtitle="Share of the expected facts each answer states (30 questions, end to end)"
          data={versions.map((r) => ({ key: r.version, value: r.metrics.fact_recall ?? null, note: r.description ?? undefined }))}
          highlight={SHIPPED}
          reference={oracle?.metrics.fact_recall != null ? { label: 'Gold passages given', value: oracle.metrics.fact_recall } : undefined}
        />
        <ColumnChart
          title="Right provision in the top 5"
          subtitle="Share of the gold provisions in the first five passages (138 questions; v7 reuses v6's retrieval)"
          data={versions.map((r) => ({ key: r.version, value: recall.get(r.version) ?? null, note: r.description ?? undefined }))}
          highlight={SHIPPED}
        />
      </div>

      <div className="table-scroll">
        <table className="metrics">
          <caption>All scores, end to end on 30 questions unless marked</caption>
          <thead>
            <tr>
              <th scope="col">Version</th>
              <th scope="col">What changed</th>
              <th scope="col">Top-5 recall<br /><small>138 questions</small></th>
              <th scope="col">Facts found</th>
              <th scope="col">Citations correct</th>
              <th scope="col">Rate tables exact</th>
              <th scope="col">Amendment type right</th>
              <th scope="col">Refusals right / caught</th>
              <th scope="col">LLM tokens per question</th>
            </tr>
          </thead>
          <tbody>
            {mini.map((r) => (
              <tr key={r.version} className={r.version === SHIPPED ? 'shipped' : undefined}>
                <th scope="row">{r.version}</th>
                <td>{r.description}</td>
                <td>{pct(recall.get(r.version))}</td>
                <td>{pct(r.metrics.fact_recall)}</td>
                <td>{pct(r.metrics.citation_precision)}</td>
                <td>{pct(r.metrics.table_exact)}</td>
                <td>{pct(r.metrics.amendment_type)}</td>
                <td>{pct(r.metrics.refusal_precision)} / {pct(r.metrics.refusal_recall)}</td>
                <td>{int(r.metrics.llm_tokens_mean)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="hint">Source: results/&lt;version&gt;/&lt;split&gt;/metrics.json. The write-up of each step is in results/ladder.md.</p>
    </div>
  )
}
