// Shared by the Act map (welcome) and the per-answer strip: the Act's sections are numbered 1-536.

export const SECTIONS = 536

/** "v2:s99(2)", "s288:tbl1#5" -> 99, 288; schedules and the preamble have no section number. */
export function sectionOf(id: string): number | null {
  const m = id.replace(/^v\d+:/, '').match(/^s(\d+)/)
  const n = m ? Number(m[1]) : NaN
  return n >= 1 && n <= SECTIONS ? n : null
}

/** When each part of the welcome sequence happens, in ms from the start. */
export const TIMELINE = {
  rows: 35,       // each row of marks appears this long after the one above
  sweep: 2300,    // the search wave starts...
  sweepFor: 1100, // ...and takes this long to cross the field
  light: 3400,    // the passages' sections light up
  end: 4600,      // nothing moves after this
}
