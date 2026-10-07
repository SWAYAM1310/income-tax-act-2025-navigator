import { useEffect, useState } from 'react'
import { reducedMotion } from '../prefs'
import { TIMELINE } from '../actmap'
import { ActMap } from './ActMap'

// A real answer, recorded from the API (e2e/fixtures/query-s99-2.sse), so the welcome needs
// no server. Its passages came from sections 99, 267, 288, 352 and 533; it cites s. 99(2).
const DEMO = {
  question: 'How was section 99(2) amended by the Finance Act, 2026?',
  answer: 'Section 99(2) was amended by substituting the reference to "sub-section (1)(a)(i) or (b)" with "sub-section (1)(a)(ii) or (b)"; the amendment was made by Act No 4 of 2026 with effect from 1-4-2026.',
  passages: [99, 267, 288, 352, 533],
  cited: 99,
}
const TYPE_FROM = 700
const TYPE_EVERY = 26
const ANSWER_FROM = TIMELINE.light + 300
const WORD_EVERY = 45
const WORDS = DEMO.answer.split(/(?<=\s)/)
const DONE = ANSWER_FROM + WORDS.length * WORD_EVERY

export function Welcome({ onStart, onLadder }: { onStart: () => void; onLadder: () => void }) {
  const [reduced] = useState(reducedMotion)
  const [t, setT] = useState(reduced ? Infinity : 0)

  // one clock for the whole sequence: the typed question, the map and the streamed answer
  useEffect(() => {
    if (reduced) return
    const start = performance.now()
    let frame = 0
    const tick = (now: number) => {
      const elapsed = now - start
      setT(elapsed >= DONE ? Infinity : elapsed)
      if (elapsed < DONE) frame = requestAnimationFrame(tick)
    }
    frame = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(frame)
  }, [reduced])

  const typed = DEMO.question.slice(0, Math.max(0, Math.floor((t - TYPE_FROM) / TYPE_EVERY)))
  const typing = typed.length < DEMO.question.length
  const status = t < TIMELINE.sweep ? null
    : t < TIMELINE.light ? 'Searching 8,108 provisions'
      : 'Kept 10 passages from 5 sections'
  const words = Math.max(0, Math.floor((t - ANSWER_FROM) / WORD_EVERY))
  const answer = WORDS.slice(0, words).join('')
  const done = t === Infinity

  return (
    <div className="flex min-h-dvh flex-col bg-bg">
      <header className="flex items-center justify-between px-4 py-4 sm:px-8">
        <span className="flex items-center gap-2.5 font-serif text-lg">
          <Mark /> Income-tax Act navigator
        </span>
        <button type="button" onClick={onStart}
          className="rounded-md px-3 py-1.5 text-sm text-ink-soft transition-colors hover:bg-raise hover:text-ink">
          Skip
        </button>
      </header>

      <main className="mx-auto grid w-full max-w-7xl flex-1 items-center gap-10 px-4 pb-10 sm:px-8 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.05fr)] lg:gap-16">
        <div className="order-2 lg:order-1">
          <h1 className="fade m-0 max-w-[14ch] font-serif text-[clamp(2.4rem,5.5vw,4.2rem)] leading-[1.04] font-medium tracking-[-0.01em]">
            Ask the Income-tax Act, 2025.
          </h1>
          <p className="fade mt-5 max-w-[46ch] text-lg text-ink-soft [animation-delay:150ms]">
            Answers come from the Act's own text, as amended by the Finance Act, 2026, and cite
            the provisions they rely on.
          </p>
          <div className="fade mt-8 flex flex-wrap gap-3 [animation-delay:300ms]">
            <button type="button" onClick={onStart}
              className="rounded-lg bg-jade px-5 py-3 font-bold text-on-jade transition-[filter] hover:brightness-110">
              Start asking
            </button>
            <button type="button" onClick={onLadder}
              className="rounded-lg border border-line-strong px-5 py-3 text-ink transition-colors hover:border-jade hover:text-jade">
              See how well it answers
            </button>
          </div>

          <section aria-label="A recorded example" className="mt-12 max-w-xl border-t border-line pt-6">
            <p className="m-0 min-h-[3.2em] font-serif text-xl leading-snug">
              {done ? DEMO.question : typed}
              {!done && typing && t >= TYPE_FROM && <span className="caret" aria-hidden="true" />}
            </p>
            <p className="mt-3 mb-0 h-5 text-sm text-ink-soft" aria-hidden={!done}>
              {done ? 'Kept 10 passages from 5 sections' : status}
            </p>
            <p className="mt-3 mb-0 min-h-[6.5em] font-serif text-[1.05rem] leading-relaxed text-ink/90">
              {done ? DEMO.answer : answer}
              {!done && words > 0 && <span className="caret" aria-hidden="true" />}
            </p>
            <p className={`mt-3 mb-0 transition-opacity duration-300 ${done ? 'opacity-100' : 'opacity-0'}`}>
              <span className="inline-block rounded-full bg-jade-tint px-3 py-1 text-sm font-bold text-jade">
                s. 99(2) <span className="font-normal">p. 131</span>
              </span>
            </p>
          </section>
        </div>

        <figure className="order-1 m-0 lg:order-2">
          <div className="mx-auto w-full max-w-[640px]">
            <ActMap passages={DEMO.passages} cited={DEMO.cited} label="s. 99(2), cited" t={t} />
          </div>
          <figcaption className="mt-3 text-sm text-ink-soft">
            Each mark is one of the Act's 536 sections. Point at one to see which.
          </figcaption>
        </figure>
      </main>

      <footer className="border-t border-line px-4 py-3 text-xs text-ink-soft sm:px-8">
        <strong className="text-refusal">Not tax advice.</strong> Answers quote the Act's text and can be
        wrong or incomplete. Read the cited provision before relying on an answer.
      </footer>
    </div>
  )
}

/** The navigator's mark: a section sign over a green rule. */
export function Mark() {
  return (
    <svg width="22" height="22" viewBox="0 0 32 32" aria-hidden="true">
      <text x="16" y="22" textAnchor="middle" fontFamily="Georgia, serif" fontSize="20" fill="currentColor">§</text>
      <rect x="7" y="26" width="18" height="2.5" rx="1.25" fill="var(--color-jade)" />
    </svg>
  )
}
