import { useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import type { Step } from '../api'
import { provisionFor, shortCite } from '../api'
import { ask, stop, useLive } from '../ask'
import type { Turn } from '../history'
import { getChat, useChats } from '../history'
import { ActStrip } from './ActMap'
import type { ComposerHandle } from './Composer'
import { Composer } from './Composer'
import { Check, Copy, Loader } from './Icons'
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
    case 'wake': return 'Woke the server (it sleeps when no one is using it)'
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

type Props = {
  chatId: string | null
  onCreated: (id: string) => void
  composer: React.RefObject<ComposerHandle | null>
  toolbar: ReactNode
}

export function ChatView({ chatId, onCreated, composer, toolbar }: Props) {
  useChats() // re-render as the history changes
  const chat = getChat(chatId)
  const live = useLive()
  const [open, setOpen] = useState<Open | null>(null)
  const thread = useRef<HTMLDivElement>(null)
  const stick = useRef(true)
  const turns = chat?.turns ?? []
  const busy = !!live && live.chatId === chatId

  // follow the stream unless the reader has scrolled up
  useEffect(() => {
    const el = thread.current
    if (el && stick.current) el.scrollTop = el.scrollHeight
  })

  useEffect(() => {
    const esc = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(null) }
    document.addEventListener('keydown', esc)
    return () => document.removeEventListener('keydown', esc)
  }, [])

  function onAsk(q: string) {
    stick.current = true
    setOpen(null)
    const id = ask(chatId, q)
    if (id && id !== chatId) onCreated(id)
  }

  return (
    <div className="relative flex h-dvh min-w-0 flex-1">
      <div className={`flex min-w-0 flex-1 flex-col transition-[margin] duration-300 ease-out ${open ? 'xl:mr-[min(44rem,44vw)]' : ''}`}>
        <header className="flex h-14 shrink-0 items-center gap-2 border-b border-line px-3">
          {toolbar}
          <h1 className="m-0 truncate text-sm font-bold text-ink-soft">{chat?.title ?? 'New chat'}</h1>
        </header>

        <div ref={thread} className="flex-1 overflow-y-auto"
          onScroll={(e) => { const el = e.currentTarget; stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80 }}>
          <div className="mx-auto w-full max-w-[46rem] px-4 pt-8 pb-10 sm:px-6">
            {turns.length === 0 && <Empty onPick={(q) => onAsk(q)} />}
            {turns.map((t) => (
              <TurnView key={t.id} t={t} open={open} setOpen={setOpen} />
            ))}
          </div>
        </div>

        <div className="shrink-0 bg-gradient-to-t from-bg via-bg to-transparent px-4 pt-2 pb-3 sm:px-6">
          <div className="mx-auto max-w-[46rem]">
            <Composer ref={composer} busy={busy} elsewhere={!!live && !busy} onAsk={onAsk} onStop={stop} />
            <p className="mt-2 mb-0 text-center text-xs text-ink-soft">
              <strong className="text-refusal">Not tax advice.</strong> Each question is answered on its own from the Act's text,
              and answers can be wrong. Read the cited provision before relying on one.
            </p>
          </div>
        </div>
      </div>

      {open && (
        <div className="fixed inset-0 z-40 hidden bg-black/60 md:block xl:hidden" onClick={() => setOpen(null)} aria-hidden="true" />
      )}
      <div className={`fixed inset-y-0 right-0 z-50 w-full border-l border-line bg-panel shadow-[-24px_0_48px_rgb(0_0_0/0.6)] transition-transform duration-300 ease-out md:w-[min(44rem,70vw)] xl:w-[min(44rem,44vw)] xl:shadow-none ${open ? 'translate-x-0' : 'pointer-events-none translate-x-full'}`}
        inert={!open}>
        {open && <StatuteSheet key={open.id} target={open} onClose={() => setOpen(null)} />}
      </div>
    </div>
  )
}

function Empty({ onPick }: { onPick: (q: string) => void }) {
  return (
    <div className="rise pt-[8vh]">
      <h2 className="m-0 font-serif text-[clamp(1.8rem,4vw,2.5rem)] leading-tight font-medium">What does the Act say?</h2>
      <p className="mt-2 text-ink-soft">Ask about a definition, a rate in a table, or how a provision was amended in 2026.</p>
      <p className="mt-8 mb-2 text-sm text-ink-soft">Try one of these</p>
      <ul className="m-0 list-none border-t border-line p-0">
        {EXAMPLES.map((x) => (
          <li key={x.q} className="border-b border-line">
            <button type="button" onClick={() => onPick(x.q)}
              className="group block w-full py-3 text-left transition-colors">
              <span className="line-clamp-2 font-serif text-[1.02rem] group-hover:text-jade">{x.q}</span>
              <small className="mt-0.5 block text-xs text-ink-soft">{x.why}</small>
            </button>
          </li>
        ))}
      </ul>
    </div>
  )
}

function TurnView({ t, open, setOpen }: { t: Turn; open: Open | null; setOpen: (o: Open) => void }) {
  const lines = t.steps.map(describe).filter((x): x is string => !!x)
  const a = t.answer
  const streaming = t.status === 'streaming'
  const failed = t.status === 'error' || !!a?.error
  const refused = !!a?.refused
  const text = a && !a.error ? a.answer : t.text

  return (
    <article className="mb-12" aria-label={t.question}>
      <h3 className="m-0 border-l-2 border-jade pl-4 font-serif text-[1.3rem] leading-snug font-medium">{t.question}</h3>

      {lines.length > 0 && (
        <ol className="mt-4 mb-0 list-none space-y-1 p-0 pl-4 text-sm text-ink-soft" aria-live="polite">
          {lines.map((l, i) => {
            const current = streaming && i === lines.length - 1 && !t.text
            return (
              <li key={i} className="fade flex items-center gap-2">
                {current ? <Loader className="spin size-3.5 text-jade" /> : <Check className="size-3.5 text-jade-dim" />}
                <span className={current ? 'text-ink' : undefined}>{l}</span>
              </li>
            )
          })}
        </ol>
      )}
      {streaming && lines.length === 0 && (
        <p className="mt-4 mb-0 flex items-center gap-2 pl-4 text-sm text-ink-soft"><Loader className="spin size-3.5 text-jade" /> Reading the question</p>
      )}

      {(text || refused) && !(failed && !text) && (
        <div className={`mt-5 ${refused ? 'border-l-2 border-refusal pl-4' : ''}`} aria-live="polite">
          {refused && <p className="m-0 mb-1.5 text-sm font-bold text-refusal">Not answered from the Act</p>}
          <p className={`m-0 font-serif text-[1.12rem] leading-[1.7] whitespace-pre-wrap ${streaming ? 'caret' : ''}`}>{text}</p>
        </div>
      )}

      {t.error && <p role="alert" className="mt-4 rounded-lg bg-refusal-tint px-3 py-2 text-sm text-refusal">{t.error}</p>}
      {t.status === 'stopped' && <p className="mt-3 text-sm text-ink-soft">Stopped before the answer was finished.</p>}

      {a && !a.error && (
        <>
          {a.citations.length > 0 && (
            <ul className="mt-4 mb-0 flex list-none flex-wrap gap-2 p-0" aria-label="Cited provisions">
              {a.citations.map((c) => {
                const target = provisionFor(c.chunk_id)
                const on = open?.chunk === c.chunk_id
                return (
                  <li key={c.chunk_id}>
                    <button type="button" aria-pressed={on} onClick={() => setOpen({ ...target, chunk: c.chunk_id })}
                      className="rounded-full border border-transparent bg-jade-tint px-3 py-1 text-sm font-bold text-jade transition-colors hover:border-jade aria-pressed:border-jade">
                      {shortCite(target.row ?? target.id)}
                      {c.page_start ? <span className="font-normal"> p. {c.page_start}</span> : null}
                    </button>
                  </li>
                )
              })}
            </ul>
          )}
          {!refused && a.citations.length === 0 && (
            <p className="mt-4 rounded-lg bg-refusal-tint px-3 py-2 text-sm text-refusal">The answer named no passage, so treat it as unsupported.</p>
          )}

          {!refused && t.evidence.length > 0 && (
            <ActStrip passages={t.evidence.map((p) => p.chunk_id)} cited={a.citations.map((c) => c.chunk_id)} />
          )}

          <div className="mt-4 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-ink-soft">
            {!refused && <CopyButton text={a.answer + (a.citations.length ? `\n\nCited: ${a.citations.map((c) => shortCite(provisionFor(c.chunk_id).row ?? provisionFor(c.chunk_id).id)).join('; ')}` : '')} />}
            <span>
              {refused && !a.evidence_tokens ? 'Refused before reading the Act'
                : a.cached ? 'Answered from cache' : `${a.llm_tokens.toLocaleString()} answer tokens`}
              {a.evidence_tokens ? `, from ${a.evidence_tokens.toLocaleString()} tokens of the Act` : ''}
              {a.route ? `. Route: ${a.route}.` : '.'}
            </span>
          </div>
        </>
      )}

      {t.evidence.length > 0 && (
        <details className="evidence group mt-4 text-sm">
          <summary className="cursor-pointer text-ink-soft hover:text-ink">Passages the answer was written from ({t.evidence.length})</summary>
          <div className="mt-2">
            {t.evidence.map((p) => {
              const target = provisionFor(p.chunk_id)
              return (
                <div key={p.chunk_id} className="border-t border-line py-2.5">
                  <button type="button" onClick={() => setOpen({ ...target, chunk: p.chunk_id })}
                    className="rounded-full bg-jade-tint px-2.5 py-0.5 text-xs font-bold text-jade hover:underline">
                    {p.label} {shortCite(target.row ?? target.id)}
                  </button>
                  <p className="mt-1.5 mb-0 line-clamp-3 font-serif text-ink-soft">{p.text}</p>
                </div>
              )
            })}
          </div>
        </details>
      )}
    </article>
  )
}

function CopyButton({ text }: { text: string }) {
  const [done, setDone] = useState(false)
  return (
    <button type="button"
      onClick={() => { void navigator.clipboard?.writeText(text).then(() => { setDone(true); setTimeout(() => setDone(false), 1500) }) }}
      className="flex items-center gap-1 rounded px-1.5 py-0.5 hover:bg-raise hover:text-ink">
      {done ? <Check className="size-3.5 text-jade" /> : <Copy className="size-3.5" />}{done ? 'Copied' : 'Copy'}
    </button>
  )
}
