import { useState } from 'react'
import { pickExamples } from '../examples'
import { ActField } from './ActMap'
import { Composer } from './Composer'

type Props = { onAsk: (q: string, from?: HTMLElement | null) => void; onChats: () => void; onLadder: () => void }

export function Welcome({ onAsk, onChats, onLadder }: Props) {
  // a definition, a rate and an amendment; the refusal example stays in the chat
  const [examples] = useState(() => pickExamples().slice(0, 3))

  return (
    <div className="relative flex min-h-dvh flex-col overflow-hidden bg-bg">
      <ActField />
      {/* keeps the words legible over the field without hiding it */}
      <div aria-hidden="true" className="pointer-events-none absolute inset-0
        bg-[radial-gradient(ellipse_62%_55%_at_50%_48%,rgb(0_0_0/0.92)_0%,rgb(0_0_0/0.72)_45%,transparent_100%)]" />

      <header className="enter relative flex items-center justify-between px-4 py-4 sm:px-8">
        <span className="flex items-center gap-2.5 font-serif text-lg"><Mark /> TaxLens</span>
        <nav className="flex items-center gap-5 text-sm text-ink-soft">
          <button type="button" onClick={onLadder} className="draw-line transition-colors hover:text-ink">How it scores</button>
          <button type="button" onClick={onChats} className="draw-line transition-colors hover:text-ink">Your chats</button>
        </nav>
      </header>

      <main className="relative flex flex-1 flex-col items-center justify-center px-4 pb-16 text-center">
        <h1 className="enter m-0 max-w-[20ch] font-serif text-balance text-[clamp(2.6rem,7vw,5rem)] leading-[1.02] font-medium tracking-[-0.025em] [animation-delay:250ms]">
          Ask the <span className="whitespace-nowrap">Income-tax</span> Act, 2025.
        </h1>
        <p className="enter mt-5 mb-0 max-w-[50ch] text-[1.05rem] text-balance text-ink-soft [animation-delay:370ms]">
          Answers come from the Act's own text, as amended by the Finance Act, 2026, and cite the
          provisions they rely on.
        </p>

        <div className="enter mt-10 w-full max-w-[40rem] text-left [animation-delay:490ms]">
          <Composer hero name="composer" busy={false} elsewhere={false} onAsk={onAsk} onStop={() => {}} />
        </div>

        <ul aria-label="Example questions"
          className="enter m-0 mt-5 flex w-full max-w-[40rem] list-none flex-col gap-0.5 p-0 text-left [animation-delay:610ms]">
          {examples.map((x) => (
            <li key={x.q}>
              <button type="button" onClick={(e) => onAsk(x.q, e.currentTarget.querySelector<HTMLElement>('.example-q'))}
                className="rail group flex w-full rounded-lg px-4 py-2 text-left hover:bg-raise/80">
                <span className="rail-text flex min-w-0 flex-1 flex-col sm:flex-row sm:items-baseline sm:gap-3">
                  <span className="example-q max-w-full truncate font-serif text-[0.98rem] text-ink/80 transition-colors group-hover:text-jade">{x.q}</span>
                  <small className="shrink-0 text-xs text-ink-soft sm:ml-auto">{x.why}</small>
                </span>
              </button>
            </li>
          ))}
        </ul>
      </main>

      <footer className="enter relative px-4 pb-4 text-center text-xs text-ink-soft [animation-delay:730ms]">
        <strong className="text-refusal">Not tax advice.</strong> Answers quote the Act and can be wrong; read the
        cited provision before relying on one.
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
