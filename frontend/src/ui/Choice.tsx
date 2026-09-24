import type { ReactNode } from 'react'

/* The answer row — Practice drills and the reading quiz asked the same
   question in two different hands until M23. Multiple choice is the
   interaction this product leans on, so it gets one exact shape. */
export type ChoiceState = 'idle' | 'chosen' | 'correct' | 'wrong' | 'muted'

const STATE: Record<ChoiceState, string> = {
  idle: 'border-rule hover:border-cobalt/60 hover:bg-cobalt-wash/60',
  chosen: 'border-cobalt bg-cobalt-wash text-cobalt-deep font-semibold',
  correct: 'border-cobalt bg-cobalt-wash text-cobalt-deep font-semibold',
  wrong: 'border-correction/60 text-correction',
  muted: 'border-rule text-ghost',
}

export function Choice({
  letter,
  state = 'idle',
  className = '',
  children,
  ...rest
}: {
  /** The drawn letter: the model's own "a)" prefixes are stripped server-side. */
  letter?: string
  state?: ChoiceState
  className?: string
  children: ReactNode
} & React.ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      className={`font-book block w-full rounded-sm border px-3.5 py-2.5 text-left text-[15px] transition-colors ${STATE[state]} ${className}`}
      {...rest}
    >
      {letter && (
        <span className="font-ui text-ghost mr-2.5 text-[11px] font-semibold">{letter}</span>
      )}
      {children}
    </button>
  )
}
