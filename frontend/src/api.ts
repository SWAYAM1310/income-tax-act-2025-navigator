// Typed client for the FastAPI app (src/statnav/api/app.py), reached through the /api proxy in
// development, or at VITE_API_BASE (the deployed API, e.g. on Railway) in a deployed build.

const BASE = (import.meta.env.VITE_API_BASE as string | undefined)?.replace(/\/$/, '') || '/api'
/** A deployed API may be asleep (Railway Serverless); keep retrying this long while it boots. */
const WAKE_MS = BASE === '/api' ? 0 : 75_000
export const REMOTE = BASE !== '/api'

const sleep = (ms: number, signal?: AbortSignal) => new Promise<void>((resolve, reject) => {
  const t = setTimeout(resolve, ms)
  signal?.addEventListener('abort', () => { clearTimeout(t); reject(new DOMException('Aborted', 'AbortError')) })
})

/**
 * fetch, retrying while a sleeping server boots: its proxy answers 502-504, or (without CORS
 * headers) the request fails outright. `onWaking` is called once, on the first retry.
 */
async function fetchAwake(url: string, init: RequestInit = {}, onWaking?: () => void): Promise<Response> {
  const until = Date.now() + WAKE_MS
  for (let n = 0; ; n++) {
    let res: Response | null = null
    try {
      res = await fetch(url, init)
      if (![502, 503, 504].includes(res.status)) return res
    } catch (err) {
      if ((err as Error).name === 'AbortError') throw err
      if (Date.now() >= until) throw err
    }
    if (Date.now() >= until) return res as Response
    if (n === 0) onWaking?.()
    await sleep(Math.min(1000 * 2 ** n, 8000), init.signal ?? undefined)
  }
}

/** The server's own message for a failed request (FastAPI puts it in `detail`). */
async function detailOf(res: Response): Promise<string> {
  const body = await res.text().catch(() => '')
  try {
    const d = (JSON.parse(body) as { detail?: unknown }).detail
    if (typeof d === 'string') return d
  } catch { /* not JSON */ }
  return body.slice(0, 200)
}

export type Step = {
  node: string
  route?: string
  in_scope?: boolean
  reason?: string | null
  terms?: string[]
  passages?: number
  tokens?: number
  definitions?: string[]
  verified?: boolean | null
  unsupported?: string[]
}

export type Passage = {
  label: string
  chunk_id: string
  provisions: string[]
  page_start: number | null
  page_end: number | null
  tokens: number
  text: string
}

export type Citation = {
  chunk_id: string
  provisions: string[]
  page_start: number | null
  page_end: number | null
}

export type AnswerPayload = {
  question: string
  version: string
  answer: string
  refused: boolean
  error: string | null
  route: string | null
  verified: boolean | null
  citations: Citation[]
  evidence_tokens: number
  llm_tokens: number
  classify_tokens: number
  cached: boolean
}

export type QueryEvent =
  | { type: 'step'; data: Step }
  | { type: 'evidence'; data: Passage[] }
  /** a piece of the answer as the model writes it; a higher `attempt` (v7 retry) starts over */
  | { type: 'token'; data: { text: string; attempt: number } }
  | { type: 'answer'; data: AnswerPayload }
  | { type: 'error'; data: { message: string } }
  | { type: 'done'; data: Record<string, never> }

/** POST /query and call `onEvent` for each server-sent event as it arrives. */
export async function streamQuery(
  question: string,
  onEvent: (e: QueryEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const res = await fetchAwake(`${BASE}/query`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ question }),
    signal,
  }, () => onEvent({ type: 'step', data: { node: 'wake' } }))
  if (!res.ok || !res.body) {
    const detail = await detailOf(res)
    throw new Error(res.status === 422 ? 'Ask a question of at least three characters.'
      : res.status === 429 ? detail
      : `The server answered ${res.status}. ${detail}`)
  }
  const reader = res.body.pipeThrough(new TextDecoderStream()).getReader()
  let buffer = ''
  for (;;) {
    const { value, done } = await reader.read()
    if (done) break
    buffer += value
    let cut: number
    while ((cut = buffer.indexOf('\n\n')) >= 0) {
      const block = buffer.slice(0, cut)
      buffer = buffer.slice(cut + 2)
      let type = 'message'
      let data = ''
      for (const line of block.split('\n')) {
        if (line.startsWith('event: ')) type = line.slice(7)
        else if (line.startsWith('data: ')) data += line.slice(6)
      }
      if (data) onEvent({ type, data: JSON.parse(data) } as QueryEvent)
    }
  }
}

export type Segment = {
  text: string
  label?: string
  type?: string | null
  was?: string | null
  endnote?: string | null
}

export type AmendedText = { segments: Segment[]; before: string | null }

export type Amendment = {
  label: string
  type: string
  amending_act: string | null
  effective_date: string | null
  endnote: string
  prior_text: string | null
  provision_id: string
  applies_to: string
}

export type Node = {
  id: string
  label: string | null
  heading: string | null
  text: string
  kind: string
  depth: number
  amended_text: AmendedText | null
}

export type TableRow = {
  row_id: string
  sl_no: string
  subrow: string | null
  row_heading: string | null
  cells: Record<string, string>
  rate: string | null
  threshold: string | null
}

export type Provision = {
  id: string
  kind: string
  number: string
  heading: string | null
  citation: string
  chapter: string | null
  schedule: string | null
  page_start: number
  page_end: number
  is_amended: boolean
  amendments: Amendment[]
  subtree: Node[]
  section: { id: string; heading: string | null; citation: string } | null
  rows?: TableRow[]
}

async function getJSON<T>(path: string): Promise<T> {
  const res = await fetchAwake(`${BASE}${path}`)
  if (res.status === 404) throw new Error('not-found')
  if (!res.ok) throw new Error(`The server answered ${res.status}.`)
  return res.json() as Promise<T>
}

export const getProvision = (id: string) =>
  getJSON<Provision>(`/provisions/${encodeURIComponent(id)}`)

export const getAmendments = (id: string) =>
  getJSON<Amendment[]>(`/amendments/${encodeURIComponent(id)}`)

export type EvalRow = {
  version: string
  description: string | null
  retrieval_only: boolean
  n: number
  complete: boolean
  metrics: Record<string, number>
  by_type: Record<string, Record<string, number>>
}

export const getEvals = (split: string) =>
  getJSON<{ split: string; versions: EvalRow[] }>(`/evals?split=${split}`)

/**
 * Which provision a retrieved chunk should open. Chunks are named after the provision they
 * anchor ("v2:s2(109)"); table rows and notes open their table, and split chunks drop "~2".
 */
export function provisionFor(chunkId: string): { id: string; row?: string } {
  const raw = chunkId.replace(/^v\d+:/, '').replace(/~\d+$/, '')
  const hash = raw.indexOf('#')
  if (hash >= 0) return { id: raw.slice(0, hash), row: raw }
  const note = raw.match(/^(.*:tbl\d+):note\d+$/)
  if (note) return { id: note[1] }
  return { id: raw }
}

/** "s2(109)" -> "s. 2(109)"; "sch:XIV:4(3)" -> "Sch. XIV, 4(3)"; "s393:tbl1" -> "s. 393, Table 1". */
export function shortCite(id: string): string {
  const table = id.match(/^s(\w+?):tbl(\d+)(?:#(.+))?$/)
  if (table) return `s. ${table[1]}, Table ${table[2]}${table[3] ? `, Sl. ${table[3]}` : ''}`
  const sch = id.match(/^sch:([IVXL]+)(?::(.+))?$/)
  if (sch) return `Sch. ${sch[1]}${sch[2] ? `, ${sch[2].replace(/:/g, ', ')}` : ''}`
  if (id.startsWith('s')) return `s. ${id.slice(1)}`
  return id
}
