import { forwardRef, useImperativeHandle, useLayoutEffect, useRef, useState } from 'react'
import { ArrowUp, Stop } from './Icons'

export type ComposerHandle = { focus: () => void; fill: (q: string) => void }

type Props = { busy: boolean; elsewhere: boolean; onAsk: (q: string) => void; onStop: () => void }

/** The question box: Enter asks, Shift+Enter starts a new line, Stop ends a streaming answer. */
export const Composer = forwardRef<ComposerHandle, Props>(function Composer({ busy, elsewhere, onAsk, onStop }, ref) {
  const [q, setQ] = useState('')
  const [tooShort, setTooShort] = useState(false)
  const box = useRef<HTMLTextAreaElement>(null)

  useImperativeHandle(ref, () => ({
    focus: () => box.current?.focus(),
    fill: (text: string) => { setQ(text); box.current?.focus() },
  }), [])

  useLayoutEffect(() => {
    const el = box.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${Math.min(el.scrollHeight, 220)}px`
  }, [q])

  function submit() {
    if (busy || elsewhere) return
    const text = q.trim()
    if (text.length < 3) { setTooShort(true); return }
    setTooShort(false)
    setQ('')
    onAsk(text)
  }

  return (
    <form className="relative" onSubmit={(e) => { e.preventDefault(); submit() }}>
      <div className="flex items-end gap-2 rounded-2xl border border-line-strong bg-panel p-2 pl-4 transition-colors focus-within:border-jade">
        <label htmlFor="q" className="sr-only">Ask about the Act</label>
        <textarea
          id="q" ref={box} rows={1} value={q}
          placeholder="Ask about the Act, e.g. Who is an assessee in default?"
          aria-describedby={tooShort ? 'q-help' : undefined}
          onChange={(e) => { setQ(e.target.value); if (tooShort) setTooShort(false) }}
          onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); submit() } }}
          className="max-h-[220px] min-h-[2.75rem] flex-1 resize-none bg-transparent py-2.5 font-serif text-[1.08rem] leading-snug outline-none placeholder:font-sans placeholder:text-[0.95rem] placeholder:text-ink-soft"
        />
        {busy ? (
          <button type="button" onClick={onStop}
            className="flex h-11 shrink-0 items-center gap-1.5 rounded-xl border border-line-strong px-3.5 text-sm font-bold hover:border-ink">
            <Stop /> Stop
          </button>
        ) : (
          <button type="submit" disabled={elsewhere}
            className="flex h-11 shrink-0 items-center gap-1.5 rounded-xl bg-jade px-4 text-sm font-bold text-on-jade transition-[filter,opacity] hover:brightness-110 disabled:opacity-40">
            <ArrowUp /> Ask
          </button>
        )}
      </div>
      {tooShort && <p id="q-help" role="alert" className="mt-1.5 mb-0 px-1 text-sm text-refusal">Ask a question of at least three characters.</p>}
      {elsewhere && !busy && <p className="mt-1.5 mb-0 px-1 text-sm text-ink-soft">Another chat is still being answered; you can ask once it finishes.</p>}
    </form>
  )
})
