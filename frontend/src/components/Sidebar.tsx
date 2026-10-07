import { useEffect, useRef, useState } from 'react'
import type { Chat } from '../history'
import { deleteChat, download, groupByDay, renameChat, toMarkdown } from '../history'
import { Chart, Close, Dots, Download, Panel, Pencil, Plus, Search, Trash } from './Icons'
import { Settings } from './Settings'
import { Mark } from './Welcome'

type Props = {
  chats: Chat[]
  current: string | null
  view: 'chat' | 'ladder'
  streamingChat: string | null
  onNew: () => void
  onOpen: (id: string) => void
  onLadder: () => void
  onHome: () => void
  onHide: () => void
}

export function Sidebar({ chats, current, view, streamingChat, onNew, onOpen, onLadder, onHome, onHide }: Props) {
  const [query, setQuery] = useState('')
  const q = query.trim().toLowerCase()
  const shown = q
    ? chats.filter((c) => c.title.toLowerCase().includes(q) || c.turns.some((t) => t.question.toLowerCase().includes(q)))
    : chats

  return (
    <nav aria-label="Chats" className="flex h-full w-full flex-col bg-panel">
      <div className="flex items-center justify-between gap-2 px-3 pt-3 pb-2">
        <button type="button" onClick={onHome} title="Show the welcome page"
          className="flex items-center gap-2 rounded-md px-1.5 py-1 font-serif text-[1.05rem] hover:bg-raise">
          <Mark /> Act navigator
        </button>
        <button type="button" onClick={onHide} aria-label="Hide the chat list"
          className="rounded-md p-2 text-ink-soft hover:bg-raise hover:text-ink">
          <Panel />
        </button>
      </div>

      <div className="px-3">
        <button type="button" onClick={onNew}
          className="flex w-full items-center gap-2 rounded-lg border border-line-strong px-3 py-2.5 text-left font-bold transition-colors hover:border-jade hover:text-jade">
          <Plus /> New chat
          <kbd className="ml-auto rounded border border-line px-1.5 text-[0.7rem] font-normal text-ink-soft">Ctrl K</kbd>
        </button>
        <label className="mt-2 flex items-center gap-2 rounded-lg bg-raise px-3 py-2 text-ink-soft focus-within:outline-2 focus-within:outline-jade">
          <Search />
          <span className="sr-only">Search chats</span>
          <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search chats"
            className="w-full bg-transparent text-sm text-ink outline-none placeholder:text-ink-soft" />
        </label>
      </div>

      <div className="mt-3 flex-1 overflow-y-auto px-2 pb-3">
        {chats.length === 0 && (
          <p className="px-2 text-sm text-ink-soft">Your questions are kept here, in this browser only.</p>
        )}
        {chats.length > 0 && shown.length === 0 && (
          <p className="px-2 text-sm text-ink-soft">No chat matches “{query}”.</p>
        )}
        {groupByDay(shown).map(([label, list]) => (
          <section key={label} className="mb-3">
            <h2 className="m-0 px-2 pb-1 text-xs font-bold text-ink-soft">{label}</h2>
            <ul className="m-0 list-none p-0">
              {list.map((c) => (
                <Row key={c.id} chat={c} active={view === 'chat' && c.id === current}
                  streaming={c.id === streamingChat} onOpen={() => onOpen(c.id)}
                  onDeleted={() => { if (c.id === current) onNew() }} />
              ))}
            </ul>
          </section>
        ))}
      </div>

      <div className="border-t border-line p-2">
        <button type="button" onClick={onLadder} aria-current={view === 'ladder' ? 'page' : undefined}
          className="flex w-full items-center gap-2.5 rounded-md px-2.5 py-2 text-left text-sm hover:bg-raise aria-[current=page]:bg-jade-tint aria-[current=page]:text-jade">
          <Chart /> How well it answers
        </button>
        <Settings />
      </div>
    </nav>
  )
}

function Row({ chat, active, streaming, onOpen, onDeleted }: {
  chat: Chat; active: boolean; streaming: boolean; onOpen: () => void; onDeleted: () => void
}) {
  const [menu, setMenu] = useState(false)
  const [mode, setMode] = useState<'view' | 'rename' | 'confirm'>('view')
  const [title, setTitle] = useState(chat.title)
  const box = useRef<HTMLLIElement>(null)

  useEffect(() => {
    if (!menu) return
    const close = (e: PointerEvent) => { if (!box.current?.contains(e.target as Node)) setMenu(false) }
    document.addEventListener('pointerdown', close)
    return () => document.removeEventListener('pointerdown', close)
  }, [menu])

  if (mode === 'rename') {
    return (
      <li className="px-1 py-0.5">
        <form onSubmit={(e) => { e.preventDefault(); renameChat(chat.id, title); setMode('view') }}>
          <label className="sr-only" htmlFor={`rename-${chat.id}`}>Chat name</label>
          <input id={`rename-${chat.id}`} autoFocus value={title} onChange={(e) => setTitle(e.target.value)}
            onBlur={() => { renameChat(chat.id, title); setMode('view') }}
            onKeyDown={(e) => { if (e.key === 'Escape') { setTitle(chat.title); setMode('view') } }}
            className="w-full rounded-md border border-jade bg-bg px-2 py-1.5 text-sm outline-none" />
        </form>
      </li>
    )
  }

  if (mode === 'confirm') {
    return (
      <li className="rounded-md bg-refusal-tint px-2.5 py-2 text-sm" role="group" aria-label="Confirm delete">
        <p className="m-0">Delete “{chat.title}”?</p>
        <div className="mt-2 flex gap-2">
          <button type="button" autoFocus onClick={() => { deleteChat(chat.id); onDeleted() }}
            className="rounded-md bg-refusal px-2.5 py-1 font-bold text-black">Delete</button>
          <button type="button" onClick={() => setMode('view')}
            className="rounded-md px-2.5 py-1 text-ink-soft hover:text-ink">Keep</button>
        </div>
      </li>
    )
  }

  return (
    <li ref={box} className="group relative">
      <button type="button" onClick={onOpen} aria-current={active ? 'page' : undefined}
        className="flex w-full items-center gap-2 rounded-md py-2 pr-9 pl-2.5 text-left text-sm text-ink/85 transition-colors hover:bg-raise hover:text-ink aria-[current=page]:bg-raise aria-[current=page]:text-ink aria-[current=page]:shadow-[inset_2px_0_0_var(--color-jade)]">
        {streaming && <span className="size-1.5 shrink-0 animate-pulse rounded-full bg-jade" aria-label="Answering" />}
        <span className="truncate">{chat.title}</span>
      </button>
      <button type="button" aria-label={`Options for ${chat.title}`} aria-expanded={menu} aria-haspopup="menu"
        onClick={() => setMenu((m) => !m)}
        className="absolute top-1/2 right-1 -translate-y-1/2 rounded p-1.5 text-ink-soft opacity-100 hover:bg-line hover:text-ink focus:opacity-100 sm:opacity-0 sm:group-hover:opacity-100 aria-expanded:opacity-100">
        <Dots />
      </button>
      {menu && (
        <div role="menu" className="rise absolute top-full right-1 z-20 w-40 rounded-lg border border-line-strong bg-raise p-1 shadow-[0_12px_32px_rgb(0_0_0/0.6)]"
          onKeyDown={(e) => { if (e.key === 'Escape') setMenu(false) }}>
          <MenuItem icon={<Pencil />} label="Rename" onClick={() => { setMenu(false); setTitle(chat.title); setMode('rename') }} />
          <MenuItem icon={<Download />} label="Export" onClick={() => { setMenu(false); download(`${slug(chat.title)}.md`, toMarkdown(chat)) }} />
          <MenuItem icon={<Trash />} label="Delete" danger onClick={() => { setMenu(false); setMode('confirm') }} />
        </div>
      )}
    </li>
  )
}

function MenuItem({ icon, label, onClick, danger }: { icon: React.ReactNode; label: string; onClick: () => void; danger?: boolean }) {
  return (
    <button type="button" role="menuitem" onClick={onClick}
      className={`flex w-full items-center gap-2 rounded-md px-2.5 py-1.5 text-left text-sm hover:bg-line ${danger ? 'text-refusal' : ''}`}>
      {icon}{label}
    </button>
  )
}

const slug = (s: string) => s.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '').slice(0, 50) || 'chat'

/** The button that brings the chat list back (desktop) or opens it as a drawer (phone). */
export function ShowSidebar({ onClick, open }: { onClick: () => void; open?: boolean }) {
  return (
    <button type="button" onClick={onClick} aria-label={open ? 'Close the chat list' : 'Show the chat list'}
      aria-expanded={open}
      className="rounded-md p-2 text-ink-soft hover:bg-raise hover:text-ink">
      {open ? <Close /> : <Panel />}
    </button>
  )
}
