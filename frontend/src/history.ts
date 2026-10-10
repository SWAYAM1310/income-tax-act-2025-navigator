// Chat history, kept in this browser's localStorage. Nothing leaves the browser: the API never
// sees earlier turns (each question is answered on its own).
import { useSyncExternalStore } from 'react'
import type { AnswerPayload, Passage, Step } from './api'
import { shortCite, provisionFor, resolveMarkers } from './api'

export type TurnStatus = 'streaming' | 'done' | 'stopped' | 'error'

export type Turn = {
  id: string
  question: string
  asked: number
  steps: Step[]
  evidence: Passage[]
  /** the answer text as it streamed in; replaced by `answer.answer` when that arrives */
  text: string
  attempt: number
  answer: AnswerPayload | null
  error: string | null
  status: TurnStatus
}

export type Chat = { id: string; title: string; created: number; updated: number; turns: Turn[] }

const KEY = 'statnav.chats.v1'
const listeners = new Set<() => void>()
let chats: Chat[] = load()
let timer: ReturnType<typeof setTimeout> | null = null

function load(): Chat[] {
  try {
    const v = JSON.parse(localStorage.getItem(KEY) ?? '[]')
    if (!Array.isArray(v)) return []
    // a page closed mid-answer leaves a turn "streaming" forever; it was stopped
    return (v as Chat[]).map((c) => ({
      ...c, turns: c.turns.map((t) => (t.status === 'streaming' ? { ...t, status: 'stopped' } : t)),
    }))
  } catch {
    return []
  }
}

function write() {
  timer = null
  let data = chats
  for (let pass = 0; pass <= data.length; pass++) {
    try {
      localStorage.setItem(KEY, JSON.stringify(data))
      return
    } catch (e) {
      if ((e as Error).name !== 'QuotaExceededError' || pass === data.length) return
      // full: drop the passage text of the oldest chats first (the answers and citations stay)
      const oldest = [...data].sort((a, b) => a.updated - b.updated)[pass]
      data = data.map((c) => (c.id !== oldest.id ? c : {
        ...c, turns: c.turns.map((t) => ({ ...t, evidence: t.evidence.map((p) => ({ ...p, text: '' })) })),
      }))
    }
  }
}

function commit(next: Chat[], now = false) {
  chats = next
  listeners.forEach((l) => l())
  if (timer) clearTimeout(timer)
  if (now) write()
  else timer = setTimeout(write, 400)
}

const uid = () => (crypto.randomUUID?.() ?? `${Date.now().toString(36)}${Math.random().toString(36).slice(2)}`)

export const titleFor = (q: string) => (q.length > 60 ? `${q.slice(0, 57).trimEnd()}…` : q)

/** All chats, most recently used first. */
export function useChats(): Chat[] {
  return useSyncExternalStore((l) => { listeners.add(l); return () => listeners.delete(l) }, () => chats)
}

export const getChat = (id: string | null) => chats.find((c) => c.id === id) ?? null

/** Start a turn (and the chat, if `chatId` is null); returns both ids. */
export function addTurn(chatId: string | null, question: string): { chatId: string; turnId: string } {
  const now = Date.now()
  const turn: Turn = { id: uid(), question, asked: now, steps: [], evidence: [], text: '', attempt: 1,
    answer: null, error: null, status: 'streaming' }
  const existing = getChat(chatId)
  const chat: Chat = existing
    ? { ...existing, updated: now, turns: [...existing.turns, turn] }
    : { id: uid(), title: titleFor(question), created: now, updated: now, turns: [turn] }
  commit([chat, ...chats.filter((c) => c.id !== chat.id)], true)
  return { chatId: chat.id, turnId: turn.id }
}

export function updateTurn(chatId: string, turnId: string, fn: (t: Turn) => Turn, now = false) {
  commit(chats.map((c) => (c.id !== chatId ? c : {
    ...c, turns: c.turns.map((t) => (t.id === turnId ? fn(t) : t)),
  })), now)
}

export function renameChat(id: string, title: string) {
  const t = title.trim()
  if (t) commit(chats.map((c) => (c.id === id ? { ...c, title: t } : c)), true)
}

export const deleteChat = (id: string) => commit(chats.filter((c) => c.id !== id), true)
export const deleteAllChats = () => commit([], true)

/** One chat as Markdown: each question, its answer and the provisions it cites. */
export function toMarkdown(c: Chat): string {
  const lines = [`# ${c.title}`, '', `_Exported ${new Date().toLocaleString()} from the Income-tax Act, 2025 navigator. Not tax advice._`, '']
  for (const t of c.turns) {
    const text = t.answer ? resolveMarkers(t.answer.answer, t.evidence) : (t.text || t.error || '(no answer)')
    // the answer's own "### " sections sit one level below the question
    lines.push(`## ${t.question}`, '', text.replace(/^#{1,5} /gm, '### '), '')
    const cites = t.answer?.citations ?? []
    if (cites.length) {
      lines.push('Cited: ' + cites.map((x) => {
        const p = provisionFor(x.chunk_id)
        return `${shortCite(p.row ?? p.id)}${x.page_start ? ` (p. ${x.page_start})` : ''}`
      }).join('; '), '')
    }
    if (t.answer?.follow_ups?.length) lines.push('Ask next:', ...t.answer.follow_ups.map((q) => `- ${q}`), '')
  }
  return lines.join('\n')
}

export function download(name: string, text: string) {
  const url = URL.createObjectURL(new Blob([text], { type: 'text/markdown' }))
  const a = Object.assign(document.createElement('a'), { href: url, download: name })
  a.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

/** Today / Yesterday / Previous 7 days / Older, newest first within each. */
export function groupByDay(list: Chat[], now = new Date()): [string, Chat[]][] {
  const day = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime()
  const groups: [string, Chat[]][] = [['Today', []], ['Yesterday', []], ['Previous 7 days', []], ['Older', []]]
  for (const c of list) {
    const i = c.updated >= day ? 0 : c.updated >= day - 864e5 ? 1 : c.updated >= day - 7 * 864e5 ? 2 : 3
    groups[i][1].push(c)
  }
  return groups.filter(([, cs]) => cs.length > 0)
}
