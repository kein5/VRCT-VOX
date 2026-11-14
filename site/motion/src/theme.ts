// Dark Studio (DESIGN.md), the same tokens as the guide's custom.css. Blue carries what you
// send and purple what comes back, as in the how-it-works diagram and the route strip.
export const C = {
  bg: '#111b2c',
  rail: '#0d1625',
  surface: '#18253b',
  raised: '#213049',
  border: '#344662',
  hairline: '#2b3b55',
  text: '#edf3ff',
  text2: '#adbed6',
  text3: '#8d9fb9',
  mine: '#6ea8ff',
  theirs: '#b48cff',
  bubble: '#edf3ff',
  bubbleText: '#111b2c',
}

// Rendered on the maintainer's PC with its local fonts; nothing is fetched.
export const FONT = "'Noto Sans JP', 'Segoe UI', 'Yu Gothic UI', sans-serif"

export type Side = 'mine' | 'theirs'
export const laneColor = (side: Side) => (side === 'mine' ? C.mine : C.theirs)
