// Reader settings (green shade, text size, motion), kept in this browser and applied as data-*
// attributes on <html>, which styles.css reads.
import { useSyncExternalStore } from 'react'

export type Prefs = {
  accent: 'jade' | 'mint' | 'forest'
  size: 's' | 'm' | 'l'
  motion: 'system' | 'reduced'
}

const KEY = 'statnav.prefs'
const DEFAULTS: Prefs = { accent: 'jade', size: 'm', motion: 'system' }

let prefs: Prefs = read()
const listeners = new Set<() => void>()

function read(): Prefs {
  try {
    return { ...DEFAULTS, ...JSON.parse(localStorage.getItem(KEY) ?? '{}') }
  } catch {
    return DEFAULTS
  }
}

export function applyPrefs(p: Prefs = prefs) {
  const el = document.documentElement
  el.dataset.accent = p.accent
  el.dataset.size = p.size
  el.dataset.motion = p.motion
}

export function setPrefs(change: Partial<Prefs>) {
  prefs = { ...prefs, ...change }
  try { localStorage.setItem(KEY, JSON.stringify(prefs)) } catch { /* settings last this visit only */ }
  applyPrefs()
  listeners.forEach((l) => l())
}

export function usePrefs(): Prefs {
  return useSyncExternalStore((l) => { listeners.add(l); return () => listeners.delete(l) }, () => prefs)
}

/** True when animation should be skipped: the reader's setting or the system's. */
export function reducedMotion(): boolean {
  if (prefs.motion === 'reduced') return true
  return typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches
}

/** A flag kept in this browser (e.g. "has seen the welcome"); false when storage is blocked. */
export function flag(name: string, set?: boolean): boolean {
  try {
    if (set !== undefined) localStorage.setItem(`statnav.${name}`, set ? '1' : '0')
    return localStorage.getItem(`statnav.${name}`) === '1'
  } catch {
    return set ?? false
  }
}
