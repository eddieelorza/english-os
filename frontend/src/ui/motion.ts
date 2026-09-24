/* The one motion law (DESIGN rule 4): everything slides along its column axis
   with an exponential ease-out. It lived in VocabularyPage until M23; it is
   the app's law, not a page's detail, so it lives here now. */
export const SLIDE = { duration: 0.32, ease: [0.16, 1, 0.3, 1] as const }

/* Two amplitudes, so a row expanding and a panel arriving are not eight
   different distances: `near` for something opening in place, `far` for
   something arriving from outside the column. */
export const NEAR = 8
export const FAR = 16

type Axis = 'y' | 'x'

/* Entrance props for a motion element: `{...slide()}` instead of restating
   initial/animate/transition (and drifting) in every file. */
export function slide(axis: Axis = 'y', distance: number = NEAR) {
  const from = { [axis]: -distance, opacity: 0 }
  const to = { [axis]: 0, opacity: 1 }
  return { initial: from, animate: to, exit: from, transition: SLIDE }
}
