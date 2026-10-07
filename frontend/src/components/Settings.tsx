import { useEffect, useRef, useState } from 'react'
import { deleteAllChats } from '../history'
import type { Prefs } from '../prefs'
import { setPrefs, usePrefs } from '../prefs'
import { Gear } from './Icons'

const ACCENTS: { key: Prefs['accent']; label: string; hex: string }[] = [
  { key: 'jade', label: 'Jade', hex: '#46d68c' },
  { key: 'mint', label: 'Mint', hex: '#7fe8b6' },
  { key: 'forest', label: 'Forest', hex: '#2fae6c' },
]

export function Settings() {
  const prefs = usePrefs()
  const [open, setOpen] = useState(false)
  const [confirm, setConfirm] = useState(false)
  const box = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const close = (e: PointerEvent) => { if (!box.current?.contains(e.target as Node)) setOpen(false) }
    const esc = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false) }
    document.addEventListener('pointerdown', close)
    document.addEventListener('keydown', esc)
    return () => { document.removeEventListener('pointerdown', close); document.removeEventListener('keydown', esc) }
  }, [open])

  return (
    <div ref={box} className="relative">
      <button type="button" aria-expanded={open} onClick={() => { setOpen((o) => !o); setConfirm(false) }}
        className="flex w-full items-center gap-2.5 rounded-md px-2.5 py-2 text-left text-sm hover:bg-raise">
        <Gear /> Settings
      </button>
      {open && (
        <div role="dialog" aria-label="Settings"
          className="rise absolute bottom-full left-0 z-30 mb-2 w-72 rounded-xl border border-line-strong bg-raise p-4 shadow-[0_16px_40px_rgb(0_0_0/0.7)]">
          <Group label="Green">
            {ACCENTS.map((a) => (
              <Choice key={a.key} on={prefs.accent === a.key} onClick={() => setPrefs({ accent: a.key })}>
                <span className="size-3 rounded-full" style={{ background: a.hex }} aria-hidden="true" />{a.label}
              </Choice>
            ))}
          </Group>
          <Group label="Text size">
            {(['s', 'm', 'l'] as const).map((s) => (
              <Choice key={s} on={prefs.size === s} onClick={() => setPrefs({ size: s })}>
                {{ s: 'Small', m: 'Medium', l: 'Large' }[s]}
              </Choice>
            ))}
          </Group>
          <Group label="Motion">
            <Choice on={prefs.motion === 'system'} onClick={() => setPrefs({ motion: 'system' })}>As the system</Choice>
            <Choice on={prefs.motion === 'reduced'} onClick={() => setPrefs({ motion: 'reduced' })}>Reduced</Choice>
          </Group>
          <div className="mt-4 border-t border-line pt-3">
            {confirm ? (
              <div className="flex items-center gap-2 text-sm">
                <span>Delete every chat?</span>
                <button type="button" autoFocus onClick={() => { deleteAllChats(); setConfirm(false); window.location.hash = '#/new' }}
                  className="rounded-md bg-refusal px-2.5 py-1 font-bold text-black">Delete all</button>
                <button type="button" onClick={() => setConfirm(false)} className="px-1.5 text-ink-soft hover:text-ink">Keep</button>
              </div>
            ) : (
              <button type="button" onClick={() => setConfirm(true)} className="text-sm text-refusal hover:underline">
                Delete all chats
              </button>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

function Group({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <fieldset className="m-0 mb-3 border-0 p-0">
      <legend className="mb-1.5 p-0 text-xs font-bold text-ink-soft">{label}</legend>
      <div className="flex flex-wrap gap-1.5">{children}</div>
    </fieldset>
  )
}

function Choice({ on, onClick, children }: { on: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button type="button" aria-pressed={on} onClick={onClick}
      className="flex items-center gap-1.5 rounded-md border border-line-strong px-2.5 py-1 text-sm hover:border-ink-soft aria-pressed:border-jade aria-pressed:bg-jade-tint aria-pressed:text-jade">
      {children}
    </button>
  )
}
