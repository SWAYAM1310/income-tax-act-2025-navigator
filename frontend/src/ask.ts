// Runs one question at a time and writes what streams in to the chat history, so an answer keeps
// arriving while the reader switches chats. The API answers one question at a time anyway.
import { useSyncExternalStore } from 'react'
import type { AnswerPayload } from './api'
import { REMOTE, streamQuery } from './api'
import { addTurn, getChat, updateTurn } from './history'

type Live = { chatId: string; turnId: string; ctl: AbortController } | null

let live: Live = null
const listeners = new Set<() => void>()
const emit = () => listeners.forEach((l) => l())

type Answered = (chatId: string, turnId: string, answer: AnswerPayload) => void
const answered = new Set<Answered>()

/** Call `fn` whenever an answer arrives (the chat view opens its first citation). */
export function onAnswered(fn: Answered): () => void {
  answered.add(fn)
  return () => { answered.delete(fn) }
}

/** The chat and turn being answered right now, if any. */
export function useLive(): Live {
  return useSyncExternalStore((l) => { listeners.add(l); return () => listeners.delete(l) }, () => live)
}

type Ids = { chatId: string; turnId: string }
/** questions asked while another answer was streaming, oldest first */
const queue: (Ids & { question: string })[] = []

/** Ask `question` in `chatId` (null starts a new chat) and return the chat id. The question is
 *  added to the chat at once; if another answer is streaming it waits (`queued`) and starts when
 *  that one ends, so a question is never dropped. */
export function ask(chatId: string | null, question: string): string {
  if (live) {
    const ids = addTurn(chatId, question, 'queued')
    queue.push({ ...ids, question })
    return ids.chatId
  }
  const ids = addTurn(chatId, question)
  run(ids, question)
  return ids.chatId
}

function run(ids: Ids, question: string) {
  const ctl = new AbortController()
  live = { ...ids, ctl }
  emit()
  const up = (fn: Parameters<typeof updateTurn>[2], now = false) => updateTurn(ids.chatId, ids.turnId, fn, now)

  void streamQuery(question, (e) => {
    switch (e.type) {
      case 'step': up((t) => ({ ...t, steps: [...t.steps, e.data] })); break
      case 'evidence': up((t) => ({ ...t, evidence: e.data })); break
      case 'token': up((t) => (e.data.attempt > t.attempt
        ? { ...t, attempt: e.data.attempt, text: e.data.text }
        : { ...t, text: t.text + e.data.text })); break
      case 'error': up((t) => ({ ...t, error: e.data.message })); break
      case 'answer': up((t) => ({
        ...t, answer: e.data, text: e.data.answer, status: e.data.error ? 'error' : 'done',
      }), true); answered.forEach((fn) => fn(ids.chatId, ids.turnId, e.data)); break
    }
  }, ctl.signal)
    .catch((err: Error) => {
      if (err.name === 'AbortError') up((t) => ({ ...t, status: 'stopped' }), true)
      else {
        // a request that never reached the server: say how to start it locally, or that it is down
        const unreachable = err instanceof TypeError
        const hint = !unreachable ? '' : REMOTE ? ' The server is not responding; try again in a minute.'
          : ' Start the API with: python -m statnav.api'
        up((t) => ({ ...t, status: 'error', error: `${err.message}${hint}` }), true)
      }
    })
    .finally(() => {
      // a stream that ends without an answer event (server stopped) is not left "streaming"
      up((t) => (t.status === 'streaming' ? { ...t, status: t.error ? 'error' : 'stopped' } : t), true)
      live = null
      // the next waiting question whose chat still exists (it may have been deleted meanwhile)
      let next = queue.shift()
      while (next && !getChat(next.chatId)?.turns.some((t) => t.id === next!.turnId)) next = queue.shift()
      if (next) {
        updateTurn(next.chatId, next.turnId, (t) => ({ ...t, status: 'streaming' }), true)
        run(next, next.question)
      } else emit()
    })
}

/** Stop what is being answered in `chatId`: the streaming answer, or questions still waiting. */
export function stop(chatId?: string | null) {
  if (!chatId || live?.chatId === chatId) { live?.ctl.abort(); return }
  for (let i = queue.length - 1; i >= 0; i--) {
    const q = queue[i]
    if (q.chatId !== chatId) continue
    queue.splice(i, 1)
    updateTurn(q.chatId, q.turnId, (t) => ({ ...t, status: 'stopped' }), true)
  }
}
