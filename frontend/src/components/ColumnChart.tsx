import { useEffect, useRef, useState } from 'react'

export type Column = { key: string; value: number | null; note?: string }

type Props = {
  title: string
  subtitle: string
  data: Column[]
  highlight?: string
  reference?: { label: string; value: number }
  format?: (v: number) => string
}

const PLOT_H = 190
const AXIS_H = 28
const LEFT = 36
const TOP = 22
const BAR_MAX = 24

/** One series of columns on a 0-1 scale: thin marks, the highlighted one in the accent, a
 * solid reference rule, hover/focus tooltips. Values also live in the table below it. */
export function ColumnChart({ title, subtitle, data, highlight, reference, format = (v) => v.toFixed(2) }: Props) {
  const box = useRef<HTMLDivElement>(null)
  const [width, setWidth] = useState(560)
  const [hover, setHover] = useState<number | null>(null)

  useEffect(() => {
    const el = box.current
    if (!el) return
    const ro = new ResizeObserver(([e]) => setWidth(Math.max(280, e.contentRect.width)))
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  const plotW = width - LEFT - 8
  const band = plotW / data.length
  const barW = Math.min(BAR_MAX, band * 0.5)
  const y = (v: number) => TOP + PLOT_H * (1 - v)
  const ticks = [0, 0.25, 0.5, 0.75, 1]
  const shown = data.filter((d) => d.value != null)
  const best = shown.reduce<Column | null>((a, d) => (!a || (d.value ?? 0) > (a.value ?? 0) ? d : a), null)

  return (
    <figure className="chart" ref={box}>
      <figcaption><strong>{title}</strong><span>{subtitle}</span></figcaption>
      <svg width={width} height={TOP + PLOT_H + AXIS_H} role="img" aria-label={`${title}. ${subtitle}`}>
        {ticks.map((t) => (
          <g key={t}>
            <line x1={LEFT} x2={width - 8} y1={y(t)} y2={y(t)} className="grid" />
            <text x={LEFT - 8} y={y(t)} dy="0.32em" textAnchor="end" className="tick">{t.toFixed(2).replace(/0$/, '')}</text>
          </g>
        ))}
        {reference && (
          <g>
            <line x1={LEFT} x2={width - 8} y1={y(reference.value)} y2={y(reference.value)} className="ref" />
            <text x={width - 8} y={y(reference.value) - 6} textAnchor="end" className="ref-label">
              {reference.label} {format(reference.value)}
            </text>
          </g>
        )}
        {data.map((d, i) => {
          const cx = LEFT + band * (i + 0.5)
          const v = d.value
          const isHi = d.key === highlight
          const labelIt = v != null && (isHi || d === best)
          return (
            <g key={d.key}
              tabIndex={v == null ? -1 : 0}
              role="graphics-symbol"
              aria-label={v == null ? `${d.key}: not measured` : `${d.key}: ${format(v)}${d.note ? `. ${d.note}` : ''}`}
              onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)}
              onFocus={() => setHover(i)} onBlur={() => setHover(null)}
              className="col">
              {/* hit target: the whole band, taller than the mark */}
              <rect x={cx - band / 2} y={TOP} width={band} height={PLOT_H} fill="transparent" />
              {v != null && v > 0 && (
                <path className={isHi ? 'bar hi' : 'bar'}
                  d={columnPath(cx - barW / 2, y(v), barW, y(0) - y(v))} />
              )}
              {labelIt && <text x={cx} y={y(v!) - 6} textAnchor="middle" className="value">{format(v!)}</text>}
              <text x={cx} y={TOP + PLOT_H + 18} textAnchor="middle"
                className={isHi ? 'xlab hi' : 'xlab'}>{d.key}</text>
            </g>
          )
        })}
      </svg>
      {hover != null && data[hover].value != null && (
        <div className="tip" style={{ left: Math.min(width - 220, Math.max(0, LEFT + band * (hover + 0.5) - 110)) }}>
          <strong>{data[hover].key}: {format(data[hover].value!)}</strong>
          {data[hover].note && <span>{data[hover].note}</span>}
        </div>
      )}
    </figure>
  )
}

/** A column with a 4px rounded top and a square base on the baseline. */
function columnPath(x: number, y: number, w: number, h: number): string {
  const r = Math.min(4, w / 2, h)
  return `M${x},${y + h} V${y + r} Q${x},${y} ${x + r},${y} H${x + w - r} Q${x + w},${y} ${x + w},${y + r} V${y + h} Z`
}
