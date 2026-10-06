import { useEffect, useState } from 'react'
import type { Node, Provision, Segment } from '../api'
import { getProvision } from '../api'

type Target = { id: string; row?: string } | null
type View = 'now' | 'before'

function Amended({ segments, view }: { segments: Segment[]; view: View }) {
  return (
    <>
      {segments.map((s, i) => {
        if (!s.label) return <span key={i}>{s.text}</span>
        if (view === 'now') {
          return (
            <span key={i}>
              <mark className="amended" title={s.endnote ?? undefined}>{s.text.trim()}</mark>
              <sup className="fn">{s.label}</sup>{' '}
            </span>
          )
        }
        if (s.was === '') return <mark key={i} className="gone">{' '}(not in the Act before) </mark>
        if (s.was) return <span key={i}><mark className="was">{s.was}</mark>{' '}</span>
        return <mark key={i} className="gone"> (earlier wording not printed) </mark>
      })}
    </>
  )
}

function NodeText({ n, view, focus }: { n: Node; view: View; focus: boolean }) {
  const a = n.amended_text
  // a whole provision substituted or omitted: its printed earlier text replaces it outright
  const wholeBefore = view === 'before' && a && a.before !== null && a.segments.every((s) => !s.label || s.was == null)
  return (
    <p className={`node${focus ? ' focus' : ''}`} style={{ marginLeft: `${Math.min(n.depth, 4) * 1.25}rem` }}>
      {n.label && <span className="lab">{n.label}</span>}
      {wholeBefore
        ? (a!.before === '' ? <mark className="gone">(this provision was not in the Act before)</mark> : <mark className="was">{a!.before}</mark>)
        : a ? <Amended segments={a.segments} view={view} /> : n.text}
    </p>
  )
}

export function StatuteSheet({ target, onClose }: { target: Target; onClose: () => void }) {
  // The parent remounts this component per provision (key={id}), so state starts fresh and the
  // effect only has to fetch.
  const [p, setP] = useState<Provision | null>(null)
  const [state, setState] = useState<'idle' | 'loading' | 'missing' | 'error'>(target ? 'loading' : 'idle')
  const [view, setView] = useState<View>('now')
  const id = target?.id

  useEffect(() => {
    if (!id) return
    let live = true
    getProvision(id)
      .then((x) => { if (live) { setP(x); setState('idle') } })
      .catch((e: Error) => { if (live) setState(e.message === 'not-found' ? 'missing' : 'error') })
    return () => { live = false }
  }, [id])

  if (!target) {
    return (
      <aside className="sheet" aria-label="Provision">
        <p className="sheet-empty">The provisions an answer cites open here, as they read in the Act, with any Finance Act, 2026 changes marked.</p>
      </aside>
    )
  }

  const amendedNodes = p?.subtree.filter((n) => n.amended_text) ?? []
  const allNotes = p?.amendments ?? []

  return (
    <aside className="sheet" aria-label="Provision" aria-busy={state === 'loading'}>
      <button className="close" type="button" onClick={onClose} aria-label="Close the provision">×</button>
      {state === 'missing' && <p className="sheet-empty">{target.id} is not a provision this navigator can show.</p>}
      {state === 'error' && <p className="sheet-empty">The provision could not be loaded. Is the API running?</p>}
      {p && (
        <>
          <header>
            <h2 className="cite">{cap(p.citation)}</h2>
            <p className="where">
              {p.chapter ? `Chapter ${p.chapter.replace('ch:', '').replace(':', ', Part ')}, ` : ''}
              {p.page_start === p.page_end ? `page ${p.page_start}` : `pages ${p.page_start}–${p.page_end}`}
            </p>
          </header>

          {amendedNodes.length > 0 && (
            <div className="amend-bar">
              <span><strong>Amended by the Finance Act, 2026.</strong> Changed words are marked.</span>
              <span className="toggle" role="group" aria-label="Show the text">
                <button type="button" aria-pressed={view === 'now'} onClick={() => setView('now')}>Now</button>
                <button type="button" aria-pressed={view === 'before'} onClick={() => setView('before')}>Before</button>
              </span>
            </div>
          )}

          <div className="page">
            <div className="marginal">{p.section?.heading ?? p.heading ?? ''}</div>
            <div className="body">
              {p.subtree.map((n) => <NodeText key={n.id} n={n} view={view} focus={n.id === target.id && p.subtree.length > 1} />)}
              {p.rows && p.rows.length > 0 && (
                <table className="rows">
                  <thead><tr><th>Sl.</th><th>Nature of payment</th><th>Rate</th><th>Threshold</th></tr></thead>
                  <tbody>
                    {p.rows.map((r) => (
                      <tr key={r.row_id} className={r.row_id === target.row ? 'focus' : undefined}>
                        <td>{r.sl_no}{r.subrow ?? ''}</td>
                        <td>{r.row_heading ?? Object.values(r.cells)[0]}</td>
                        <td>{r.rate ?? '—'}</td>
                        <td>{r.threshold ?? '—'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </div>

          {allNotes.length > 0 && (
            <section className="endnotes" aria-label="Endnotes">
              <h3>Endnotes</h3>
              <ol>
                {allNotes.map((a) => (
                  <li key={`${a.label}-${a.applies_to}`}>
                    <span className="num">{a.label}</span>
                    {cap(a.type)} in {a.applies_to}
                    {a.effective_date ? `, with effect from ${a.effective_date}` : ''}.{' '}
                    <q>{a.endnote}</q>
                  </li>
                ))}
              </ol>
            </section>
          )}
        </>
      )}
    </aside>
  )
}

const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1)
