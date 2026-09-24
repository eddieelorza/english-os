import { useEffect, useState } from 'react'
import { fmt } from './ui'
import { api } from './api'
import type { LibraryDay } from './api'
import { dayLabel } from './ReadingPage'

/* The archive at the foot of a practice tab: what you made, filed by day,
   with the same ruled grammar as the shelves. Kept collapsed so it never
   competes with today's work. */
export default function History({
  kind,
  emptyLabel,
}: {
  kind: 'writing' | 'speaking' | 'activities'
  emptyLabel: string
}) {
  const [days, setDays] = useState<LibraryDay[] | null>(null)
  const [open, setOpen] = useState(false)
  const [confirming, setConfirming] = useState<number | null>(null)

  function load() {
    api
      .library(kind === 'activities' ? undefined : kind)
      .then((d) => setDays(d.days.filter((x) => x[kind].length > 0)))
      .catch(() => setDays([]))
  }

  useEffect(load, [kind])

  async function remove(id: number) {
    if (confirming !== id) {
      setConfirming(id)
      window.setTimeout(() => setConfirming((c) => (c === id ? null : c)), 4000)
      return
    }
    setConfirming(null)
    if (kind === 'activities') await api.deleteActivity(id).catch(() => undefined)
    else await api.deleteText(id).catch(() => undefined)
    load()
  }

  const total = days?.reduce((n, d) => n + d[kind].length, 0) ?? 0

  return (
    <section className="border-rule mt-12 border-t pt-5">
      <button
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-baseline justify-between gap-4"
        aria-expanded={open}
      >
        <span className="text-[12px] font-semibold tracking-[0.18em] uppercase">
          Everything you've made
        </span>
        <span className="tnum text-ghost text-[12px]">
          {total > 0 ? `${fmt(total)} · ${open ? 'hide' : 'show'}` : emptyLabel}
        </span>
      </button>

      {open && days && (
        <div className="mt-5">
          {days.map((day) => (
            <div key={day.date} className="mb-6">
              <h4 className="border-rule-strong text-ghost border-b pb-1 text-[10px] font-semibold tracking-[0.2em] uppercase">
                {dayLabel(day.date)}
              </h4>
              <ul>
                {day[kind].map((item) => (
                  <li
                    key={item.id}
                    className="border-rule group flex items-baseline gap-4 border-b py-2.5 pr-1"
                  >
                    <span className="font-book min-w-0 flex-1 truncate text-[14px]">
                      {item.title}
                    </span>
                    <span className="tnum text-ghost shrink-0 text-[11px]">
                      {'score' in item && item.score != null
                        ? `${fmt(item.score)}/${fmt(item.total ?? 0)}`
                        : 'words_produced' in item && item.words_produced != null
                          ? `${fmt(item.words_produced)} words · ${fmt(item.errors_count ?? 0)} corrections`
                          : ''}
                    </span>
                    <button
                      onClick={() => remove(item.id)}
                      aria-label="Delete"
                      className={`shrink-0 text-[10px] font-semibold tracking-[0.14em] uppercase transition-opacity ${
                        confirming === item.id
                          ? 'text-correction opacity-100'
                          : 'text-ghost hover:text-correction opacity-0 group-hover:opacity-100'
                      }`}
                    >
                      {confirming === item.id ? 'Sure?' : 'Delete'}
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      )}
    </section>
  )
}
