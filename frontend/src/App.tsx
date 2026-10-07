import { useEffect, useRef, useState } from 'react'
import { useLive } from './ask'
import { getChat, useChats } from './history'
import { flag } from './prefs'
import { ChatView } from './components/ChatView'
import type { ComposerHandle } from './components/Composer'
import { LadderView } from './components/LadderView'
import { ShowSidebar, Sidebar } from './components/Sidebar'
import { Welcome } from './components/Welcome'

type Route = { view: 'welcome' } | { view: 'chat'; id: string | null } | { view: 'ladder' }

function fromHash(): Route {
  const h = window.location.hash
  if (h === '#/ladder' || h === '#ladder') return { view: 'ladder' }
  if (h === '#/welcome') return { view: 'welcome' }
  const m = h.match(/^#\/c\/(.+)$/)
  if (m && getChat(m[1])) return { view: 'chat', id: m[1] }
  if (h === '#/new' || m || flag('seenWelcome')) return { view: 'chat', id: null }
  return { view: 'welcome' }
}

const go = (hash: string) => { if (window.location.hash !== hash) window.location.hash = hash }

export default function App() {
  const [route, setRoute] = useState<Route>(fromHash)
  const chats = useChats()
  const live = useLive()
  const [hidden, setHidden] = useState(() => flag('sidebarHidden'))
  const [drawer, setDrawer] = useState(false)
  const composer = useRef<ComposerHandle>(null)

  useEffect(() => {
    const on = () => { setRoute(fromHash()); setDrawer(false) }
    window.addEventListener('hashchange', on)
    return () => window.removeEventListener('hashchange', on)
  }, [])

  // Ctrl/Cmd+K: new chat; "/": type a question; Esc: close the drawer
  useEffect(() => {
    const keys = (e: KeyboardEvent) => {
      const typing = (e.target as HTMLElement)?.closest?.('input, textarea, [contenteditable]')
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault(); flag('seenWelcome', true); go('#/new'); setTimeout(() => composer.current?.focus(), 0)
      } else if (e.key === '/' && !typing) {
        e.preventDefault(); composer.current?.focus()
      } else if (e.key === 'Escape') setDrawer(false)
    }
    document.addEventListener('keydown', keys)
    return () => document.removeEventListener('keydown', keys)
  }, [])

  const start = () => { flag('seenWelcome', true); go('#/new'); setRoute({ view: 'chat', id: null }) }

  if (route.view === 'welcome') {
    return <Welcome onStart={start} onLadder={() => { flag('seenWelcome', true); go('#/ladder') }} />
  }

  const hide = (h: boolean) => { flag('sidebarHidden', h); setHidden(h) }
  const sidebar = (
    <Sidebar
      chats={chats}
      current={route.view === 'chat' ? route.id : null}
      view={route.view}
      streamingChat={live?.chatId ?? null}
      onNew={() => { go('#/new'); setDrawer(false); setTimeout(() => composer.current?.focus(), 0) }}
      onOpen={(id) => { go(`#/c/${id}`); setDrawer(false) }}
      onLadder={() => { go('#/ladder'); setDrawer(false) }}
      onHome={() => go('#/welcome')}
      onHide={() => { if (drawer) setDrawer(false); else hide(true) }}
    />
  )
  const toolbar = (
    <>
      <span className="md:hidden"><ShowSidebar onClick={() => setDrawer(true)} /></span>
      {hidden && <span className="hidden md:inline"><ShowSidebar onClick={() => hide(false)} /></span>}
    </>
  )

  return (
    <div className="flex h-dvh overflow-hidden">
      {!hidden && <aside className="hidden w-[16.5rem] shrink-0 border-r border-line md:flex">{sidebar}</aside>}

      {/* phones: the chat list is a drawer */}
      <div className={`fixed inset-0 z-50 md:hidden ${drawer ? '' : 'pointer-events-none'}`} inert={!drawer}>
        <div className={`absolute inset-0 bg-black/70 transition-opacity duration-200 ${drawer ? 'opacity-100' : 'opacity-0'}`}
          onClick={() => setDrawer(false)} aria-hidden="true" />
        <aside className={`absolute inset-y-0 left-0 flex w-[85vw] max-w-[20rem] border-r border-line transition-transform duration-300 ease-out ${drawer ? 'translate-x-0' : '-translate-x-full'}`}>
          {sidebar}
        </aside>
      </div>

      {route.view === 'chat' ? (
        <ChatView key={route.id ?? 'new'} chatId={route.id} composer={composer} toolbar={toolbar}
          onCreated={(id) => { go(`#/c/${id}`); setRoute({ view: 'chat', id }) }} />
      ) : (
        <div className="flex h-dvh min-w-0 flex-1 flex-col">
          <header className="flex h-14 shrink-0 items-center gap-2 border-b border-line px-3">
            {toolbar}
            <h1 className="m-0 text-sm font-bold text-ink-soft">How well it answers</h1>
          </header>
          <main className="flex-1 overflow-y-auto"><LadderView /></main>
        </div>
      )}
    </div>
  )
}
