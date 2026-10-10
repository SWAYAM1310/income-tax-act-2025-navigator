// Outline icons (Lucide geometry, 24px grid, 1.75 stroke). Decorative unless given a label.
import type { ReactNode, SVGProps } from 'react'

function Icon({ children, ...p }: SVGProps<SVGSVGElement> & { children: ReactNode }) {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75"
      strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" {...p}>{children}</svg>
  )
}

type P = SVGProps<SVGSVGElement>
export const Plus = (p: P) => <Icon {...p}><path d="M12 5v14M5 12h14" /></Icon>
export const Search = (p: P) => <Icon {...p}><circle cx="11" cy="11" r="7" /><path d="m20 20-3.5-3.5" /></Icon>
export const Menu = (p: P) => <Icon {...p}><path d="M4 6h16M4 12h16M4 18h16" /></Icon>
export const Panel = (p: P) => <Icon {...p}><rect x="3" y="4" width="18" height="16" rx="2" /><path d="M9 4v16" /></Icon>
export const Dots = (p: P) => <Icon {...p}><circle cx="5" cy="12" r="1" /><circle cx="12" cy="12" r="1" /><circle cx="19" cy="12" r="1" /></Icon>
export const Gear = (p: P) => <Icon {...p}><circle cx="12" cy="12" r="3" /><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" /></Icon>
export const Chart = (p: P) => <Icon {...p}><path d="M4 20V10M10 20V4M16 20v-7M22 20H2" /></Icon>
export const Copy = (p: P) => <Icon {...p}><rect x="9" y="9" width="12" height="12" rx="2" /><path d="M5 15H4a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1h10a1 1 0 0 1 1 1v1" /></Icon>
export const Check = (p: P) => <Icon {...p}><path d="M20 6 9 17l-5-5" /></Icon>
export const Stop = (p: P) => <Icon {...p}><rect x="7" y="7" width="10" height="10" rx="1.5" fill="currentColor" /></Icon>
export const ArrowUp = (p: P) => <Icon {...p}><path d="M12 19V5M5 12l7-7 7 7" /></Icon>
export const Close = (p: P) => <Icon {...p}><path d="M18 6 6 18M6 6l12 12" /></Icon>
export const Download = (p: P) => <Icon {...p}><path d="M12 3v12M7 10l5 5 5-5M5 21h14" /></Icon>
export const Pencil = (p: P) => <Icon {...p}><path d="M17 3a2.85 2.85 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z" /></Icon>
export const Trash = (p: P) => <Icon {...p}><path d="M3 6h18M8 6V4h8v2M19 6l-1 14H6L5 6" /></Icon>
export const Loader = (p: P) => <Icon {...p}><path d="M21 12a9 9 0 1 1-6.22-8.56" /></Icon>
export const Bulb = (p: P) => <Icon {...p}><path d="M9 18h6M10 22h4M12 2a7 7 0 0 0-4 12.7c.6.5 1 1.2 1 2V17h6v-.3c0-.8.4-1.5 1-2A7 7 0 0 0 12 2Z" /></Icon>
export const Reply = (p: P) => <Icon {...p}><path d="M9 14 4 9l5-5" /><path d="M4 9h10.5a5.5 5.5 0 0 1 0 11H11" /></Icon>
