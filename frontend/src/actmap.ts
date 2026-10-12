// The welcome page draws the Act as a field of dots, one per section (sections 1-536, in order).

export const SECTIONS = 536

/** When each part of the welcome field's entrance happens, in ms from the start. */
export const TIMELINE = {
  rows: 22,        // each row of dots appears this long after the one above
  sweep: 700,      // one jade wave starts...
  sweepFor: 1500,  // ...and takes this long to cross the field
  end: 2800,       // nothing moves after this unless the pointer does
}
