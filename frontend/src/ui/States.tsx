import type { ReactNode } from 'react'
import { Button } from './Button'
import { useDelayed } from './cache'

/* Loading, waiting, failing and empty — the four states every lesson has and
   each one used to draw differently (M23). They speak in the book voice and
   they announce themselves, because the local model takes 15–80 s and a
   silent screen reads as a hung one. */

/* DESIGN rule 7: skeletons are faint ruled lines, never grey blocks. The page
   that is loading already looks like the page that arrives. */
export function RuledSkeleton({
  lines = 3,
  className = '',
}: {
  lines?: number
  className?: string
}) {
  /* Ragged on purpose: equal widths read as a table, not as prose. */
  const widths = ['w-full', 'w-11/12', 'w-3/4', 'w-10/12', 'w-2/3', 'w-5/6']
  return (
    <div
      aria-hidden
      className={`mt-10 animate-pulse space-y-5 motion-reduce:animate-none ${className}`}
    >
      {Array.from({ length: lines }, (_, i) => (
        <div key={i} className={`bg-rule h-px ${widths[i % widths.length]}`} />
      ))}
    </div>
  )
}

/* The shaped version. `RuledSkeleton` stands in for prose; this stands in for
   a LIST, and it reserves the height of the rows that are coming — a
   three-line skeleton replaced by five 56px rows is a page that jumps.

   Still DESIGN rule 7: a hairline per row and two faint ticks where the label
   and the count will be. No blocks, no shimmer, no spinner. It waits 140 ms
   before drawing, because a skeleton that flashes reads as a glitch. */
export function RowsSkeleton({
  rows = 5,
  rowClass = 'h-14',
  className = '',
}: {
  rows?: number
  rowClass?: string
  className?: string
}) {
  const shown = useDelayed(true)
  const widths = ['w-40', 'w-56', 'w-32', 'w-48', 'w-44', 'w-36']
  return (
    <div
      role="status"
      aria-busy="true"
      aria-label="Loading"
      className={`border-rule border-b ${className}`}
    >
      {Array.from({ length: rows }, (_, i) => (
        <div
          key={i}
          className={`border-rule flex items-center justify-between border-t ${rowClass}`}
        >
          {shown && (
            <>
              <div
                className={`bg-rule h-px animate-pulse motion-reduce:animate-none ${widths[i % widths.length]}`}
              />
              <div className="bg-rule h-px w-8 animate-pulse motion-reduce:animate-none" />
            </>
          )}
        </div>
      ))}
    </div>
  )
}

/* Something is being written by the coach. Ghost italic, announced politely,
   and able to carry the queue note the generators already write. */
export function Waiting({ children, note }: { children: ReactNode; note?: ReactNode }) {
  return (
    <div role="status" aria-live="polite" className="mt-6">
      <p className="font-book text-ghost text-[15px] italic">{children}</p>
      {note && <p className="font-book text-ghost mt-1 text-[13px] italic">{note}</p>}
    </div>
  )
}

/* An error names the problem and offers the way out. `onRetry` is not
   optional decoration: a line with no action is where a session ends. */
export function ErrorLine({
  children,
  onRetry,
  retryLabel = 'Try again',
  className = '',
}: {
  children: ReactNode
  onRetry?: () => void
  retryLabel?: string
  className?: string
}) {
  return (
    <div role="alert" className={`mt-8 ${className}`}>
      <p className="font-book text-correction text-[15px] italic">{children}</p>
      {onRetry && (
        <Button variant="text" tone="cobalt" onClick={onRetry} className="mt-2">
          {retryLabel}
        </Button>
      )}
    </div>
  )
}

/* The page that has nothing on it still speaks in the book voice
   ("This page of the ledger is blank."), with the way out underneath. */
export function Empty({ children, hint }: { children: ReactNode; hint?: ReactNode }) {
  return (
    <div className="mt-10">
      <p className="font-book text-ink-soft text-lg italic">{children}</p>
      {hint && <p className="text-ghost mt-2 text-[12px]">{hint}</p>}
    </div>
  )
}
