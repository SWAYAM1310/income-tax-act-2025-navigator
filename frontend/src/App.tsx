import { useEffect, useState } from 'react'
import { AskView } from './components/AskView'
import { LadderView } from './components/LadderView'

type Tab = 'ask' | 'ladder'

function fromHash(): Tab {
  return window.location.hash === '#ladder' ? 'ladder' : 'ask'
}

export default function App() {
  const [tab, setTab] = useState<Tab>(fromHash)

  useEffect(() => {
    const on = () => setTab(fromHash())
    window.addEventListener('hashchange', on)
    return () => window.removeEventListener('hashchange', on)
  }, [])

  const go = (t: Tab) => { window.location.hash = t === 'ask' ? '' : 'ladder'; setTab(t) }

  return (
    <>
      <header className="masthead">
        <h1>Income-tax Act, 2025 <span>as amended by the Finance Act, 2026</span></h1>
        <nav className="tabs" aria-label="Views">
          <button type="button" aria-current={tab === 'ask' ? 'page' : undefined} onClick={() => go('ask')}>Ask the Act</button>
          <button type="button" aria-current={tab === 'ladder' ? 'page' : undefined} onClick={() => go('ladder')}>How well it answers</button>
        </nav>
      </header>
      <p className="caveat">
        <strong>Not tax advice.</strong> Answers quote the Act's text and can be wrong or
        incomplete. Read the cited provision before relying on an answer.
      </p>
      <main>{tab === 'ask' ? <AskView /> : <LadderView />}</main>
    </>
  )
}
