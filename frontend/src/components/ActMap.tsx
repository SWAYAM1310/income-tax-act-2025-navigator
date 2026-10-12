// The Act as a field of dots, one per section, behind the welcome page. Rows fade in and one
// jade wave crosses it on load; after that it moves only for the pointer: dots near the cursor
// glow (the nearest one names its section) and a tap or click sends a ripple out.
import { useEffect, useRef } from 'react'
import { SECTIONS, TIMELINE } from '../actmap'
import { reducedMotion } from '../prefs'

const REACH = 150     // px: how far the cursor's glow reaches
const RIPPLE_MS = 1400
const RIPPLE_SPEED = 0.5  // px per ms

const css = (name: string) => getComputedStyle(document.documentElement).getPropertyValue(name).trim()

function rgb(hex: string): number[] {
  const h = hex.replace('#', '')
  return [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16))
}

function mix(a: number[], b: number[], t: number): string {
  return `rgb(${a.map((v, i) => Math.round(v + (b[i] - v) * t)).join(' ')})`
}

const clamp = (v: number) => Math.min(1, Math.max(0, v))

export function ActField() {
  const canvas = useRef<HTMLCanvasElement>(null)

  useEffect(() => {
    const el = canvas.current
    const ctx = el?.getContext('2d')
    if (!el || !ctx) return
    const still = reducedMotion()
    const jade = rgb(css('--color-jade') || '#46d68c')
    const dot = rgb(css('--color-dot') || '#1a241e')
    const ink = css('--color-ink-soft') || '#9aa89f'
    const font = css('--font-sans') || 'system-ui'
    const glow = new Float32Array(SECTIONS)
    const ripples: { x: number; y: number; at: number }[] = []
    let pointer: { x: number; y: number; mouse: boolean } | null = null
    let w = 0, h = 0, cols = 1, rows = 1, cell = 1, ox = 0, oy = 0
    const start = performance.now()
    let frame = 0

    function layout() {
      const r = el!.getBoundingClientRect()
      w = r.width; h = r.height
      const dpr = window.devicePixelRatio || 1
      el!.width = Math.round(w * dpr); el!.height = Math.round(h * dpr)
      ctx!.setTransform(dpr, 0, 0, dpr, 0, 0)
      // as many columns as make the cells square for this screen's shape
      cols = Math.max(8, Math.round(Math.sqrt((SECTIONS * w) / Math.max(h, 1))))
      rows = Math.ceil(SECTIONS / cols)
      cell = Math.min(w / cols, h / rows)
      ox = (w - cell * cols) / 2 + cell / 2
      oy = (h - cell * rows) / 2 + cell / 2
    }

    /** One frame; true while something is still moving. */
    function draw(now: number): boolean {
      const t = still ? Infinity : now - start
      ctx!.clearRect(0, 0, w, h)
      const front = ((t - TIMELINE.sweep) / TIMELINE.sweepFor) * (cols + rows)
      const waving = t >= TIMELINE.sweep && t < TIMELINE.sweep + TIMELINE.sweepFor + 600
      let busy = t < TIMELINE.end
      while (ripples.length && now - ripples[0].at > RIPPLE_MS) ripples.shift()
      if (ripples.length) busy = true
      let nearest = -1, nearestD = Infinity

      for (let i = 0; i < SECTIONS; i++) {
        const r = Math.floor(i / cols), c = i % cols
        const x = ox + c * cell, y = oy + r * cell
        const appear = clamp((t - r * TIMELINE.rows) / 400)
        if (appear <= 0) continue

        let target = 0
        if (pointer) {
          const d = Math.hypot(x - pointer.x, y - pointer.y)
          if (d < REACH) target = (1 - d / REACH) ** 2
          if (d < nearestD) { nearestD = d; nearest = i }
        }
        for (const p of ripples) {
          const age = now - p.at
          const off = Math.hypot(x - p.x, y - p.y) - age * RIPPLE_SPEED
          target = Math.max(target, 0.85 * Math.exp(-(off * off) / 900) * (1 - age / RIPPLE_MS))
        }
        glow[i] += (target - glow[i]) * (still ? 1 : 0.14)
        if (Math.abs(target - glow[i]) > 0.004) busy = true

        let wave = 0
        if (waving) {
          const d = front - (c + r)
          wave = 0.6 * Math.exp(-(d * d) / 6) * (t < TIMELINE.sweep + TIMELINE.sweepFor ? 1 : 0)
        }
        const k = Math.min(1, Math.max(glow[i], wave))
        ctx!.globalAlpha = appear
        ctx!.fillStyle = mix(dot, jade, k)
        ctx!.beginPath()
        ctx!.arc(x, y, Math.max(1.4, cell * (0.065 + 0.1 * k)), 0, Math.PI * 2)
        ctx!.fill()
      }
      ctx!.globalAlpha = 1

      // the dot under the cursor names its section
      if (pointer?.mouse && nearest >= 0 && nearestD < cell * 0.7) {
        const x = ox + (nearest % cols) * cell, y = oy + Math.floor(nearest / cols) * cell
        ctx!.font = `12px ${font}`
        ctx!.fillStyle = ink
        ctx!.textAlign = x > w - 120 ? 'right' : 'left'
        ctx!.fillText(`Section ${nearest + 1}`, x + (x > w - 120 ? -cell * 0.4 : cell * 0.4), y - cell * 0.4)
      }
      return busy
    }

    const loop = (now: number) => { frame = draw(now) ? requestAnimationFrame(loop) : 0 }
    const kick = () => { if (!frame) frame = requestAnimationFrame(loop) }

    layout()
    const resize = new ResizeObserver(() => { layout(); if (still) draw(performance.now()); else kick() })
    resize.observe(el)
    if (still) { draw(performance.now()); return () => resize.disconnect() }

    const at = (e: PointerEvent) => {
      const r = el.getBoundingClientRect()
      return { x: e.clientX - r.left, y: e.clientY - r.top }
    }
    const move = (e: PointerEvent) => { pointer = { ...at(e), mouse: e.pointerType === 'mouse' }; kick() }
    const down = (e: PointerEvent) => { ripples.push({ ...at(e), at: performance.now() }); kick() }
    const up = (e: PointerEvent) => { if (e.pointerType !== 'mouse') { pointer = null; kick() } }
    const leave = () => { pointer = null; kick() }
    window.addEventListener('pointermove', move)
    window.addEventListener('pointerdown', down)
    window.addEventListener('pointerup', up)
    document.documentElement.addEventListener('pointerleave', leave)
    kick()
    return () => {
      cancelAnimationFrame(frame)
      resize.disconnect()
      window.removeEventListener('pointermove', move)
      window.removeEventListener('pointerdown', down)
      window.removeEventListener('pointerup', up)
      document.documentElement.removeEventListener('pointerleave', leave)
    }
  }, [])

  return (
    <canvas ref={canvas} role="img" aria-label="The Act as 536 sections, one dot each"
      className="absolute inset-0 size-full" />
  )
}
