// The Act as a field of marks, one per section (sections 1-536, in order). The welcome page
// animates it; each answer shows the same field as a strip of where its passages came from.
import { useEffect, useRef, useState } from 'react'
import { SECTIONS, TIMELINE, sectionOf } from '../actmap'

const css = (name: string) => getComputedStyle(document.documentElement).getPropertyValue(name).trim()

function mix(a: string, b: string, t: number): string {
  const p = (h: string) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16))
  const [x, y] = [p(a), p(b)]
  const k = Math.min(1, Math.max(0, t))
  return `#${x.map((v, i) => Math.round(v + (y[i] - v) * k).toString(16).padStart(2, '0')).join('')}`
}

type MapProps = {
  /** sections the demo answer's passages came from, and the one it cites */
  passages: number[]
  cited: number
  /** shown beside the cited mark, e.g. "s. 99(2), cited" */
  label: string
  /** ms into the welcome sequence (TIMELINE); Infinity draws the final frame */
  t: number
}

export function ActMap({ passages, cited, label, t }: MapProps) {
  const canvas = useRef<HTMLCanvasElement>(null)
  const [hover, setHover] = useState<{ n: number; x: number; y: number } | null>(null)
  const geo = useRef({ cols: 24, cell: 16, ox: 0, oy: 0 })
  const hoverRef = useRef<number | null>(null)
  const draw = useRef<(t: number) => void>(() => {})
  const last = useRef(t)

  useEffect(() => {
    const el = canvas.current!
    const ctx = el.getContext('2d')
    if (!ctx) return
    const lit = new Set(passages)

    draw.current = (t: number) => {
      last.current = t
      const { cols, cell, ox, oy } = geo.current
      const dpr = window.devicePixelRatio || 1
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
      ctx.clearRect(0, 0, el.width, el.height)
      const jade = css('--color-jade') || '#46d68c'
      const dim = css('--color-jade-dim') || '#1f5a3c'
      const base = '#18211c'
      const size = cell * 0.62
      const rows = Math.ceil(SECTIONS / cols)
      const front = ((t - TIMELINE.sweep) / TIMELINE.sweepFor) * (cols + rows)
      for (let i = 0; i < SECTIONS; i++) {
        const n = i + 1
        const r = Math.floor(i / cols)
        const c = i % cols
        const appear = Math.min(1, Math.max(0, (t - r * TIMELINE.rows) / 300))
        if (appear <= 0) continue
        let color = base
        if (t >= TIMELINE.sweep && t < TIMELINE.light + 400) {
          const d = front - (c + r)
          color = mix(base, jade, 0.55 * Math.exp(-(d * d) / 10) * (t < TIMELINE.light ? 1 : 1 - (t - TIMELINE.light) / 400))
        }
        if (t >= TIMELINE.light && (lit.has(n) || n === cited)) {
          const k = Math.min(1, (t - TIMELINE.light) / 250)
          color = n === cited ? mix(base, jade, k) : mix(base, mix(dim, jade, 0.35), k)
        }
        if (hoverRef.current === n) color = mix(color, '#e9f0ea', 0.5)
        ctx.globalAlpha = appear
        ctx.fillStyle = color
        const x = ox + c * cell + (cell - size) / 2
        const y = oy + r * cell + (cell - size) / 2
        ctx.beginPath()
        ctx.roundRect(x, y, size, size, Math.min(3, size / 4))
        ctx.fill()
        // one ring opens once around the cited section
        if (n === cited && t >= TIMELINE.light && t < TIMELINE.light + 900) {
          const k = (t - TIMELINE.light) / 900
          ctx.globalAlpha = 1 - k
          ctx.strokeStyle = jade
          ctx.lineWidth = 1.5
          ctx.beginPath()
          ctx.arc(x + size / 2, y + size / 2, size * (0.8 + k * 2.2), 0, Math.PI * 2)
          ctx.stroke()
        }
      }
      // name the cited section beside its mark
      if (t >= TIMELINE.light + 250) {
        const i = cited - 1
        const x = ox + (i % cols) * cell + cell
        const y = oy + Math.floor(i / cols) * cell + cell / 2
        ctx.globalAlpha = Math.min(1, (t - TIMELINE.light - 250) / 300)
        ctx.font = `600 ${Math.max(11, Math.round(cell * 0.62))}px Spectral, Georgia, serif`
        ctx.textBaseline = 'middle'
        const w = ctx.measureText(label).width
        const right = x + 8 + w + 8 <= ox + cols * cell
        const lx = right ? x + 1 : x - cell - 1 - w - 10
        ctx.fillStyle = 'rgba(0,0,0,0.85)'
        ctx.beginPath()
        ctx.roundRect(lx, y - cell * 0.5, w + 10, cell, 4)
        ctx.fill()
        ctx.fillStyle = jade
        ctx.fillText(label, lx + 5, y + 1)
      }
      ctx.globalAlpha = 1
    }

    const fit = () => {
      // the width sets the cell size; the height follows from the number of rows
      const box = el.parentElement!.getBoundingClientRect()
      const cols = box.width < 480 ? 24 : 26
      const rows = Math.ceil(SECTIONS / cols)
      const cell = Math.max(8, Math.min(box.width / cols, 26))
      const dpr = window.devicePixelRatio || 1
      el.width = Math.round(box.width * dpr)
      el.height = Math.round(rows * cell * dpr)
      el.style.width = `${box.width}px`
      el.style.height = `${el.height / dpr}px`
      geo.current = { cols, cell, ox: (box.width - cols * cell) / 2, oy: 0 }
      draw.current(last.current)
    }
    fit()
    const ro = new ResizeObserver(fit)
    ro.observe(el.parentElement!)

    return () => ro.disconnect()
  }, [passages, cited, label])

  // the parent's clock moves the sequence; nothing changes after TIMELINE.end
  useEffect(() => {
    if (t <= TIMELINE.end || last.current < TIMELINE.end) draw.current(t)
  }, [t])

  function onMove(e: React.PointerEvent<HTMLCanvasElement>) {
    const rect = e.currentTarget.getBoundingClientRect()
    const { cols, cell, ox, oy } = geo.current
    const c = Math.floor((e.clientX - rect.left - ox) / cell)
    const r = Math.floor((e.clientY - rect.top - oy) / cell)
    const n = c >= 0 && c < cols && r >= 0 ? r * cols + c + 1 : 0
    const next = n >= 1 && n <= SECTIONS ? n : null
    if (next !== hoverRef.current) {
      hoverRef.current = next
      draw.current(last.current)
    }
    setHover(next ? { n: next, x: ox + c * cell + cell / 2, y: oy + r * cell } : null)
  }

  return (
    <div className="relative w-full">
      <canvas
        ref={canvas}
        role="img"
        aria-label={`A map of the Act: ${SECTIONS} marks, one per section. The sample answer's passages come from sections ${passages.join(', ')}; it cites section ${cited}.`}
        onPointerMove={onMove}
        onPointerDown={onMove}
        onPointerLeave={() => { hoverRef.current = null; setHover(null); draw.current(last.current) }}
      />
      {hover && (
        <div className="pointer-events-none absolute z-10 -translate-x-1/2 -translate-y-full whitespace-nowrap rounded-md border border-line-strong bg-raise px-2 py-1 text-xs text-ink"
          style={{ left: hover.x, top: hover.y - 6 }}>
          Section {hover.n}
          {hover.n === cited ? ', cited' : passages.includes(hover.n) ? ', a passage' : ''}
        </div>
      )}
    </div>
  )
}

/** The same field flattened to one line: where an answer's passages sit among the 536 sections. */
export function ActStrip({ passages, cited }: { passages: string[]; cited: string[] }) {
  const p = new Set(passages.map(sectionOf).filter((n): n is number => n != null))
  const c = new Set(cited.map(sectionOf).filter((n): n is number => n != null))
  if (p.size === 0 && c.size === 0) return null
  const x = (n: number) => `${((n - 0.5) / SECTIONS) * 100}%`
  const all = [...new Set([...p, ...c])].sort((a, b) => a - b)
  return (
    <figure className="m-0 mt-5">
      <svg width="100%" height="30" role="img" className="block overflow-visible"
        aria-label={`Where the passages sit in the Act: sections ${all.join(', ')}${c.size ? `; cited: ${[...c].join(', ')}` : ''}.`}>
        <line x1="0" x2="100%" y1="11" y2="11" stroke="var(--color-line-strong)" />
        {[1, 100, 200, 300, 400, 536].map((n) => (
          <g key={n}>
            <line x1={x(n)} x2={x(n)} y1="16" y2="19" stroke="var(--color-line-strong)" />
            <text x={x(n)} y="29" fontSize="10" fill="var(--color-ink-soft)"
              textAnchor={n === 1 ? 'start' : n === 536 ? 'end' : 'middle'}>{n}</text>
          </g>
        ))}
        {all.map((n) => (
          <rect key={n} x={x(n)} y={c.has(n) ? 2 : 5} width="3" height={c.has(n) ? 14 : 8} rx="1"
            transform="translate(-1.5 0)" fill="var(--color-jade)" opacity={c.has(n) ? 1 : 0.5}>
            <title>Section {n}{c.has(n) ? ', cited' : ''}</title>
          </rect>
        ))}
      </svg>
      <figcaption className="mt-0.5 text-xs text-ink-soft">
        Where the passages sit among the Act's 536 sections{c.size ? '; the cited ones are tallest' : ''}.
      </figcaption>
    </figure>
  )
}
