// Typed client for the FastAPI app (src/statnav/api/app.py), reached through the /api proxy.

const BASE = '/api'

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
  | { type: 'answer'; data: AnswerPayload }
  | { type: 'error'; data: { message: string } }
  | { type: 'done'; data: Record<string, never> }

/** POST /query and call `onEvent` for each server-sent event as it arrives. */
export async function streamQuery(
  question: string,
  onEvent: (e: QueryEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const res = await fetch(`${BASE}/query`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ question }),
    signal,
  })
  if (!res.ok || !res.body) {
    const detail = await res.text().catch(() => '')
    throw new Error(res.status === 422 ? 'Ask a question of at least three characters.'
      : `The server answered ${res.status}. ${detail.slice(0, 200)}`)
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
  const res = await fetch(`${BASE}${path}`)
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
