import { useEffect, useState } from 'react'
import { api } from './api'
import type { DayBlockKey, DayPlan } from './api'
import { ButtonLink, Section } from './ui'

export default function SessionNext({
  after,
  hideFor,
}: {
  after: DayBlockKey
  hideFor?: readonly DayBlockKey[]
}) {
  const [plan, setPlan] = useState<DayPlan | null>(null)

  useEffect(() => {
    let live = true
    api.day()
      .then((day) => {
        if (live) setPlan(day)
      })
      .catch(() => undefined)
    return () => {
      live = false
    }
  }, [])

  if (!plan || plan.paused || !plan.blocks.length) return null
  const next = plan.next
  if (next && (next.key === after || hideFor?.includes(next.key))) return null

  return (
    <Section className="font-ui text-left">
      <p className="font-book text-ink-soft text-base leading-relaxed">
        {next
          ? `Next in today's session: ${next.title} — ${next.detail}`
          : "That's today's session."}
      </p>
      {next ? (
        <ButtonLink to={next.route} className="mt-4">Go on →</ButtonLink>
      ) : (
        <ButtonLink to="/" variant="text" tone="cobalt" className="mt-4">
          Back to Today
        </ButtonLink>
      )}
    </Section>
  )
}
