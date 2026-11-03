/* The motion law (DESIGN rule 4): things slide along their column axis with an
   exponential ease-out, at one of three speeds. `micro` answers a touch,
   `component` opens something in place, `page` brings something from outside
   the column. index.css carries the same curve and `micro` for CSS transitions. */
export const EASE = [0.16, 1, 0.3, 1] as const
export const DUR = { micro: 0.12, component: 0.2, page: 0.28 } as const

export const SLIDE = { duration: DUR.component, ease: EASE }

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
