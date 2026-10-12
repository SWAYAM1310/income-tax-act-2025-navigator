import { forwardRef, useImperativeHandle, useLayoutEffect, useRef, useState } from 'react'
import { ArrowUp, Stop } from './Icons'

export type ComposerHandle = { focus: () => void; fill: (q: string) => void }

type Props = {
  busy: boolean; elsewhere: boolean; onStop: () => void
  /** `from` is the text box, so the welcome page can fly the question out of it */
  onAsk: (q: string, from?: HTMLElement | null) => void
  /** the larger box on the welcome page */
  hero?: boolean
  /** view-transition-name, so the box glides between the welcome page and the chat */
  name?: string
}

/** The question box: Enter asks, Shift+Enter starts a new line, Stop ends a streaming answer. */
export const Composer = forwardRef<ComposerHandle, Props>(function Composer({ busy, elsewhere, onAsk, onStop, hero, name }, ref) {
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
    // the welcome page leaves for the chat with the question still in the box, so the transition
    // can carry it to the answer
    if (!hero) setQ('')
    onAsk(text, box.current)
  }

  return (
    <form className="relative" style={name ? { viewTransitionName: name } : undefined} onSubmit={(e) => { e.preventDefault(); submit() }}>
      <div className={`flex items-end gap-2 rounded-[1.4rem] border border-line-strong bg-panel/85 p-2 shadow-[0_18px_50px_-20px_rgb(0_0_0/0.9)] backdrop-blur-md transition-[border-color,box-shadow] duration-300 hover:border-jade-dim focus-within:border-jade focus-within:shadow-[0_0_0_3px_color-mix(in_srgb,var(--color-jade)_16%,transparent),0_18px_50px_-20px_rgb(0_0_0/0.9)] ${hero ? 'pl-5' : 'pl-4'}`}>
        <label htmlFor="q" className="sr-only">Ask about the Act</label>
        <textarea
          id="q" ref={box} rows={1} value={q}
          placeholder="Ask about the Act, e.g. Who is an assessee in default?"
          aria-describedby={tooShort ? 'q-help' : undefined}
          onChange={(e) => { setQ(e.target.value); if (tooShort) setTooShort(false) }}
          onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); submit() } }}
          className={`max-h-[220px] flex-1 resize-none bg-transparent font-serif leading-snug outline-none placeholder:font-sans placeholder:text-ink-soft ${hero ? 'min-h-[3.25rem] py-3 text-[1.15rem] placeholder:text-[1rem]' : 'min-h-[2.75rem] py-2.5 text-[1.08rem] placeholder:text-[0.95rem]'}`}
        />
        {busy ? (
          <button type="button" onClick={onStop}
            className="flex h-11 shrink-0 items-center gap-1.5 rounded-full border border-line-strong px-4 text-sm font-bold transition-colors hover:border-ink">
            <Stop /> Stop
          </button>
        ) : (
          <button type="submit" disabled={elsewhere} aria-label="Ask" title="Ask (Enter)"
            className={`sheen group grid shrink-0 place-items-center rounded-full bg-jade text-on-jade disabled:opacity-40 ${hero ? 'size-12' : 'size-11'}`}>
            <ArrowUp className="transition-transform duration-300 group-hover:-translate-y-0.5" strokeWidth={2.25} />
          </button>
        )}
      </div>
      {tooShort && <p id="q-help" role="alert" className="mt-1.5 mb-0 px-1 text-sm text-refusal">Ask a question of at least three characters.</p>}
      {elsewhere && !busy && <p className="mt-1.5 mb-0 px-1 text-sm text-ink-soft">Another chat is still being answered; you can ask once it finishes.</p>}
    </form>
  )
})
