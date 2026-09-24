import type { ReactNode } from 'react'

/* Three page measures, not four ad-hoc ones (M23):
   - `study`    the work you do one thing at a time — Review, Practice, Writing,
                Speaking, Shadowing, Podcast, the Reader.
   - `evidence` the day and its record — Today, Stats.
   - `ledger`   the long ruled lists you scan — Vocabulary, Reading.
   The horizontal padding grows with the measure so the outer margin reads the
   same on every lesson. */
const WIDTH = {
  study: 'max-w-2xl px-5 sm:px-6',
  evidence: 'max-w-3xl px-4 sm:px-6 lg:px-10',
  ledger: 'max-w-4xl px-4 sm:px-6 lg:px-12',
} as const

export type PageWidth = keyof typeof WIDTH

export function Page({
  width = 'study',
  bottom = 'pb-20',
  className = '',
  children,
}: {
  width?: PageWidth
  /** The Reader wants more foot room; Review fills the viewport instead. */
  bottom?: string
  className?: string
  children: ReactNode
}) {
  return (
    <div className={`mx-auto ${WIDTH[width]} pt-10 lg:pt-14 ${bottom} ${className}`}>
      {children}
    </div>
  )
}

/* The lesson masthead. `overline` is the world's own kicker (the Assimil
   course label), `meta` the right-aligned tabular fact — counts, never a
   second heading. */
export function PageHeader({
  overline,
  title,
  subtitle,
  meta,
  serif = false,
}: {
  overline?: ReactNode
  title: ReactNode
  subtitle?: ReactNode
  meta?: ReactNode
  /** A text's own title speaks in the book voice; a lesson name does not. */
  serif?: boolean
}) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-x-8 gap-y-3">
      <div className="min-w-0">
        {overline && (
          <p className="text-ghost text-[11px] font-semibold tracking-[0.16em] uppercase">
            {overline}
          </p>
        )}
        {serif ? (
          <h2 className="font-book mt-1 text-3xl leading-tight font-semibold">{title}</h2>
        ) : (
          <h2 className="mt-1 text-4xl font-extrabold tracking-tight">{title}</h2>
        )}
        {subtitle && <div className="font-book text-ink-soft mt-2 text-[14px]">{subtitle}</div>}
      </div>
      {meta && <div className="text-ink-soft shrink-0 text-right text-[13px]">{meta}</div>}
    </div>
  )
}

/* Rules, not cards (DESIGN rule 6): a section is a hairline and air. */
export function Section({
  label,
  right,
  className = '',
  children,
}: {
  label?: ReactNode
  right?: ReactNode
  className?: string
  children: ReactNode
}) {
  return (
    <section className={`border-rule mt-8 border-t pt-6 ${className}`}>
      {(label || right) && (
        <div className="mb-4 flex items-baseline justify-between gap-4">
          {label && (
            <h3 className="text-[11px] font-semibold tracking-[0.16em] uppercase">{label}</h3>
          )}
          {right && <span className="text-ghost text-[12px]">{right}</span>}
        </div>
      )}
      {children}
    </section>
  )
}
