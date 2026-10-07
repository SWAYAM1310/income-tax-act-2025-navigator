// Runs one question at a time and writes what streams in to the chat history, so an answer keeps
// arriving while the reader switches chats. The API answers one question at a time anyway.
import { useSyncExternalStore } from 'react'
import type { AnswerPayload } from './api'
import { REMOTE, streamQuery } from './api'
import { addTurn, updateTurn } from './history'

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

/** Ask `question` in `chatId` (null starts a new chat). Returns the chat id, or null if busy. */
export function ask(chatId: string | null, question: string): string | null {
  if (live) return null
  const ids = addTurn(chatId, question)
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
      emit()
    })
  return ids.chatId
}

export function stop() {
  live?.ctl.abort()
}
