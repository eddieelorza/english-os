import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'

/* One button family (M23). Before this there were 65 class-strings and six
   different solid primaries; the shape of an action never told you what it
   did. Three families now — solid, ruled, bare — plus one reserved danger
   outline for the correction red. */
const BASE = 'font-semibold uppercase transition-colors disabled:cursor-default'

const VARIANT = {
  primary:
    'bg-cobalt text-paper hover:bg-cobalt-deep rounded-sm tracking-[0.14em] disabled:opacity-40',
  secondary:
    'border border-rule-strong text-ink-soft hover:border-cobalt/50 hover:text-cobalt-deep rounded-sm tracking-[0.14em] disabled:opacity-40',
  danger:
    'border border-correction text-correction hover:bg-correction/5 rounded-sm tracking-[0.14em] disabled:opacity-40',
  /* The apparatus voice: a word in the margin, not a control with a box. */
  text: 'tracking-[0.14em] disabled:opacity-30',
} as const

const PADDING = { sm: 'px-4 py-1.5', md: 'px-5 py-2' } as const
const SIZE = { sm: 'text-[11px]', md: 'text-[12px]' } as const

/* Bare buttons carry the tone instead of a fill. */
const TONE = {
  ghost: 'text-ghost hover:text-ink-soft',
  cobalt: 'text-cobalt-deep hover:text-cobalt',
  correction: 'text-correction hover:text-correction/80',
} as const

export type ButtonVariant = keyof typeof VARIANT
export type ButtonTone = keyof typeof TONE

interface Common {
  variant?: ButtonVariant
  size?: 'sm' | 'md'
  tone?: ButtonTone
  className?: string
  children: ReactNode
}

function classes({
  variant = 'primary',
  size = 'md',
  tone = 'ghost',
  className = '',
}: Omit<Common, 'children'>) {
  const shape = variant === 'text' ? `${TONE[tone]} min-h-6` : PADDING[size]
  return `${BASE} ${VARIANT[variant]} ${SIZE[size]} ${shape} ${className}`
}

export function Button({
  variant,
  size,
  tone,
  className,
  children,
  ...rest
}: Common & React.ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button className={classes({ variant, size, tone, className })} {...rest}>
      {children}
    </button>
  )
}

/* Same face, different element: a destination is a link, so it opens in a new
   tab, gets copied, and shows its URL — behaviour a button silently loses. */
export function ButtonLink({
  to,
  variant,
  size,
  tone,
  className,
  children,
  ...rest
}: Common & { to: string } & Omit<React.ComponentProps<typeof Link>, 'to' | 'className'>) {
  return (
    <Link to={to} className={`inline-block ${classes({ variant, size, tone, className })}`} {...rest}>
      {children}
    </Link>
  )
}
