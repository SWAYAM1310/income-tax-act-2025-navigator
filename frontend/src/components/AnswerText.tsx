// An answer's text. v9 writes a small, fixed slice of Markdown ("### " headings, "- " or "1. "
// bullets, **bold**) with [Cn] citation markers; older answers are one plain paragraph, which
// renders exactly as before. The text may be half-streamed, so nothing here can assume a
// marker, a bold run or a section is complete.
import type { ReactNode } from 'react'
import type { Passage } from '../api'
import { markLabel, provisionFor, shortCite } from '../api'
import { Bulb } from './Icons'

type Open = { id: string; row?: string; chunk: string }

type Block =
  | { kind: 'para'; text: string }
  | { kind: 'list'; ordered: boolean; items: string[] }
type Section = { heading: string | null; blocks: Block[] }

const HEADING = /^#{1,6}\s+(.*)$/
const BULLET = /^\s*[-*•]\s+(.*)$/
const NUMBERED = /^\s*\d+[.)]\s+(.*)$/

/** Split the text into sections at its headings, and each section into paragraphs and lists. */
function parseAnswer(text: string): Section[] {
  const sections: Section[] = [{ heading: null, blocks: [] }]
  let para: string[] = []
  const cur = () => sections[sections.length - 1]
  const flush = () => {
    if (para.length) cur().blocks.push({ kind: 'para', text: para.join(' ') })
    para = []
  }
  for (const raw of text.split('\n')) {
    const line = raw.trimEnd()
    const h = line.match(HEADING)
    const b = line.match(BULLET)
    const n = b ? null : line.match(NUMBERED)
    if (h) {
      flush()
      sections.push({ heading: h[1].replace(/\*\*/g, '').trim(), blocks: [] })
    } else if (b || n) {
      flush()
      const ordered = !b
      const last = cur().blocks[cur().blocks.length - 1]
      const item = (b ?? n)![1]
      if (last?.kind === 'list' && last.ordered === ordered) last.items.push(item)
      else cur().blocks.push({ kind: 'list', ordered, items: [item] })
    } else if (!line.trim()) {
      flush()
    } else {
      para.push(line.trim())
    }
  }
  flush()
  // follow-up questions belong under the answer as buttons; a model that also writes them as a
  // section of the text would show them twice
  return sections.filter((s) => (s.heading !== null || s.blocks.length)
    && !/^(follow\W?ups?|ask next)\b/i.test(s.heading ?? ''))
}

type Props = {
  text: string
  evidence: Passage[]
  streaming: boolean
  open: Open | null
  onCite: (o: Open) => void
}

export function AnswerText({ text, evidence, streaming, open, onCite }: Props) {
  // a marker or bold run still arriving is held back until it is complete
  const shown = streaming ? text.replace(/\s*\[\s*C?\s*\d*\s*$/, '') : text
  // Key terms waits for the final answer: the server drops any term no passage defines
  const sections = parseAnswer(shown).filter((s) => !(streaming && /^key terms\b/i.test(s.heading ?? '')))
  const plain = sections.length === 1 && sections[0].heading === null
  let last = 0
  sections.forEach((s) => s.blocks.forEach(() => { last++ }))
  let n = 0
  const caretOn = () => (streaming && ++n === last ? 'caret' : undefined)

  const inline = (t: string) => <Inline text={t} evidence={evidence} open={open} onCite={onCite} />
  const blocks = (bs: Block[]) => bs.map((b, i) => b.kind === 'para'
    ? <p key={i} className={`my-2 ${caretOn() ?? ''}`}>{inline(b.text)}</p>
    : (() => {
        const cls = `my-2 space-y-1.5 pl-6 marker:text-jade-dim ${b.ordered ? 'list-decimal' : 'list-disc'} ${caretOn() ?? ''}`
        const items = b.items.map((it, j) => <li key={j} className="pl-1">{inline(it)}</li>)
        return b.ordered ? <ol key={i} className={cls}>{items}</ol> : <ul key={i} className={cls}>{items}</ul>
      })())

  if (plain) {
    // one paragraph (v0-v8, refusals): the original rendering, line breaks kept
    return (
      <p className={`m-0 font-serif text-[1.12rem] leading-[1.7] whitespace-pre-wrap ${streaming ? 'caret' : ''}`}>
        {inline(shown)}
      </p>
    )
  }
  return (
    <div className="answer font-serif text-[1.08rem] leading-[1.7]">
      {sections.map((s, i) => {
        const example = /^example/i.test(s.heading ?? '')
        if (example) {
          return (
            <section key={i} className="mt-6 flex gap-3 rounded-lg border border-line border-l-2 border-l-jade bg-raise px-4 py-3">
              <Bulb className="mt-1.5 size-4 shrink-0 text-jade" />
              <div className="min-w-0 flex-1 [&>*:first-child]:mt-0 [&>*:last-child]:mb-0">
                <h4 className="m-0 font-sans text-xs font-bold tracking-wide text-jade uppercase">{s.heading}</h4>
                {blocks(s.blocks)}
              </div>
            </section>
          )
        }
        return (
          <section key={i}>
            {s.heading && <h4 className={`m-0 font-serif text-[1.12rem] font-semibold ${i === 0 ? '' : 'mt-6'}`}>{s.heading}</h4>}
            {blocks(s.blocks)}
          </section>
        )
      })}
      {streaming && last === 0 && <span className="caret" />}
    </div>
  )
}

/** One line of text: **bold** runs and clickable [Cn] markers. */
function Inline({ text, evidence, open, onCite }: { text: string; evidence: Passage[]; open: Open | null; onCite: (o: Open) => void }) {
  const out: ReactNode[] = []
  let prev = ''
  // an unmatched ** (still streaming, or a stray one) is dropped rather than shown
  const t = (text.match(/\*\*/g)?.length ?? 0) % 2 ? text.replace(/\*\*(?!.*\*\*)/, '') : text
  // the model sometimes writes "[ C1 ]"
  t.split(/(\*\*[^*]+\*\*|\s*\[\s*C\s*\d+\s*\])/g).forEach((part, i) => {
    if (!part) return
    const bold = part.match(/^\*\*([^*]+)\*\*$/)
    const cite = part.match(/^\s*\[\s*C\s*(\d+)\s*\]$/)
    if (bold) out.push(<strong key={i} className="font-semibold">{bold[1]}</strong>)
    else if (cite) {
      const p = evidence.find((e) => e.label === `C${cite[1]}`)
      if (!p) return // a label with no passage (or not yet arrived) shows nothing
      const target = provisionFor(p.chunk_id)
      const label = markLabel(target.row ?? target.id)
      if (label === prev) return // [C1][C2] in the same section reads as one mark
      prev = label
      const on = open?.chunk === p.chunk_id
      out.push(
        <sup key={i} className="ml-0.5 leading-none">
          <button type="button" aria-pressed={on} onClick={() => onCite({ ...target, chunk: p.chunk_id })}
            title={`${shortCite(target.row ?? target.id)}${p.page_start ? `, p. ${p.page_start}` : ''}`}
            aria-label={`Open ${shortCite(target.row ?? target.id)}`}
            className="cite rounded px-0.5 font-sans text-[0.7em] font-bold text-jade hover:bg-jade-tint hover:underline aria-pressed:bg-jade-tint">
            {label}
          </button>
        </sup>,
      )
      return
    } else {
      if (part.trim()) prev = ''
      out.push(part)
    }
  })
  return <>{out}</>
}
