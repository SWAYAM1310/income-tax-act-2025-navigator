import { useRef, useState } from 'react'
import type { AnswerPayload, Passage, Step } from '../api'
import { provisionFor, shortCite, streamQuery } from '../api'
import { StatuteSheet } from './StatuteSheet'

// Questions from the eval set, verbatim (so their answers replay from cache), one per route.
const EXAMPLES = [
  { q: 'What is the meaning of "transfer" under the Income-tax Act, 2025?', why: 'A definition' },
  { q: 'Under section 393, what are the TDS rate and the threshold limit for payment on transfer of certain immovable property other than agricultural land: Any consideration for transfer of any immovable property (other than agricultural land) when paid by person, where the payee is a resident?', why: 'A rate table' },
  { q: 'How was section 99(2) amended by the Finance Act, 2026?', why: 'An amendment' },
  { q: 'How do I claim a refund that is stuck on the portal?', why: 'Outside the Act, so it is refused' },
]

/** What each agent step did, in the reader's words. */
function describe(s: Step): string | null {
  switch (s.node) {
    case 'classify':
      return s.in_scope === false
        ? "Checked the question: it is not about the Act's text"
        : 'Checked the question is about the Act'
    case 'refuse': return 'Refused without searching'
    case 'retrieve': return `Searched the Act: ${s.passages} passages`
    case 'tools': return s.definitions?.length
      ? `Put the defining clause first (${s.definitions.map(shortCite).join(', ')})` : null
    case 'pack': return `Kept ${s.passages} passages, ${s.tokens?.toLocaleString()} tokens`
    case 'generate': return 'Wrote the answer from those passages'
    case 'verify': return s.verified === false
      ? 'Checked the claims: some were unsupported, so it rewrote the answer'
      : 'Checked every claim against the passages'
    default: return null
  }
}

type Open = { id: string; row?: string; chunk: string }

export function AskView() {
  const [question, setQuestion] = useState('')
  const [busy, setBusy] = useState(false)
  const [steps, setSteps] = useState<Step[]>([])
  const [evidence, setEvidence] = useState<Passage[]>([])
  const [answer, setAnswer] = useState<AnswerPayload | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [open, setOpen] = useState<Open | null>(null)
  const abort = useRef<AbortController | null>(null)

  async function ask(q: string) {
    const text = q.trim()
    if (text.length < 3 || busy) return
    abort.current?.abort()
    const ctl = new AbortController()
    abort.current = ctl
    setQuestion(text); setBusy(true); setSteps([]); setEvidence([]); setAnswer(null)
    setError(null); setOpen(null)
    try {
      await streamQuery(text, (e) => {
        if (e.type === 'step') setSteps((s) => [...s, e.data])
        else if (e.type === 'evidence') setEvidence(e.data)
        else if (e.type === 'error') setError(e.data.message)
        else if (e.type === 'answer') {
          setAnswer(e.data)
          const first = e.data.citations[0]
          if (first && !e.data.refused) setOpen({ ...provisionFor(first.chunk_id), chunk: first.chunk_id })
        }
      }, ctl.signal)
    } catch (err) {
      if ((err as Error).name !== 'AbortError') {
        setError(`${(err as Error).message} Start the API with: python -m statnav.api`)
      }
    } finally {
      setBusy(false)
    }
  }

  const lines = steps.map(describe).filter((x): x is string => !!x)
  const failed = answer?.error

  return (
    <div className="workspace">
      <section className="dialogue" aria-label="Ask a question">
        <form className="ask" onSubmit={(e) => { e.preventDefault(); void ask(question) }}>
          <label htmlFor="q">What does the Act say?</label>
          <textarea
            id="q" value={question} placeholder="e.g. Who is an assessee in default?"
            onChange={(e) => setQuestion(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); void ask(question) } }}
          />
          <div className="ask-row">
            <button className="primary" type="submit" disabled={busy || question.trim().length < 3}>
              {busy ? 'Reading the Act' : 'Ask'}
            </button>
            <span className="hint">Answers quote the Act and cite the provisions they rely on.</span>
          </div>
        </form>

        {!answer && !busy && steps.length === 0 && (
          <div className="examples">
            <p>Try one of these</p>
            {EXAMPLES.map((x) => (
              <button key={x.q} type="button" onClick={() => void ask(x.q)}>
                {x.q}<small>{x.why}</small>
              </button>
            ))}
          </div>
        )}

        {lines.length > 0 && (
          <ol className="trace" aria-live="polite">
            {lines.map((l, i) => (
              <li key={i} className={busy && i === lines.length - 1 ? 'current' : undefined}>{l}</li>
            ))}
          </ol>
        )}

        {error && <p className="error" role="alert">{error}</p>}

        {answer && !failed && (
          <article className={`answer${answer.refused ? ' refused' : ''}`} aria-live="polite">
            {answer.refused && <p className="verdict">Not answered from the Act</p>}
            <p className="text">{answer.answer}</p>
            {answer.citations.length > 0 && (
              <ul className="cites" aria-label="Cited provisions">
                {answer.citations.map((c) => {
                  const target = provisionFor(c.chunk_id)
                  return (
                    <li key={c.chunk_id}>
                      <button
                        type="button" className="chip" aria-pressed={open?.chunk === c.chunk_id}
                        onClick={() => setOpen({ ...target, chunk: c.chunk_id })}
                      >
                        {shortCite(target.row ?? target.id)}
                        {c.page_start ? <span> p. {c.page_start}</span> : null}
                      </button>
                    </li>
                  )
                })}
              </ul>
            )}
            {!answer.refused && answer.citations.length === 0 && (
              <p className="error">The answer named no passage, so treat it as unsupported.</p>
            )}
            <p className="meta">
              {answer.refused && !answer.evidence_tokens ? 'Refused before reading the Act'
                : answer.cached ? 'Answered from cache' : `${answer.llm_tokens.toLocaleString()} answer tokens`}
              {answer.evidence_tokens ? `, from ${answer.evidence_tokens.toLocaleString()} tokens of the Act` : ''}
              {answer.route ? `. Route: ${answer.route}.` : '.'}
            </p>
          </article>
        )}

        {evidence.length > 0 && (
          <details className="evidence">
            <summary>Passages the answer was written from ({evidence.length})</summary>
            {evidence.map((p) => {
              const target = provisionFor(p.chunk_id)
              return (
                <div className="passage" key={p.chunk_id}>
                  <button type="button" className="chip"
                    onClick={() => setOpen({ ...target, chunk: p.chunk_id })}>
                    {p.label} {shortCite(target.row ?? target.id)}
                  </button>
                  <p>{p.text}</p>
                </div>
              )
            })}
          </details>
        )}
      </section>

      <div className={`sheet-wrap${open ? ' open' : ''}`}>
        <StatuteSheet key={open?.id ?? "none"} target={open} onClose={() => setOpen(null)} />
      </div>
    </div>
  )
}
