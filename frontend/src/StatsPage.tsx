import { useEffect, useState } from 'react'
import { api } from './api'
import type { BaselineLatest, ExperimentsSummary, Stats } from './api'
import { Link } from 'react-router-dom'
import { ErrorLine, Page, PageHeader, RuledSkeleton, fmt } from './ui'

/* The check-in's latest estimates, one line. Its own fetch: if it fails the
   stats still render. */
function CheckInLine() {
  const [latest, setLatest] = useState<BaselineLatest | null>(null)
  const [failed, setFailed] = useState(false)
  useEffect(() => {
    api.baseline().then(setLatest).catch(() => setFailed(true))
  }, [])
  if (failed || !latest) return null
  const parts = [
    latest.vocab && `vocabulary ~${fmt(latest.vocab.size)} words (${latest.vocab.cefr})`,
    latest.dictation && `dictation up to ${latest.dictation.band}`,
  ].filter(Boolean)
  return (
    <section className="border-rule mt-8 flex flex-wrap items-baseline justify-between gap-x-6 gap-y-1 border-b pb-3">
      <h3 className="text-sm font-bold tracking-tight">Check-in</h3>
      <p className="font-book text-ink-soft min-w-0 flex-1 text-sm">
        {parts.length ? `Estimates, not levels: ${parts.join(' · ')}.` : 'Not taken yet.'}
      </p>
      <Link to="/check-in" className="text-cobalt-deep text-sm font-semibold hover:underline">
        Open check-in →
      </Link>
    </section>
  )
}

/* E1/E2 as they fill in: words per group and delayed-test results. Raw
   counts, no verdict — with one learner a difference needs many words. */
function ExperimentsLines() {
  const [s, setS] = useState<ExperimentsSummary | null>(null)
  useEffect(() => {
    api.experiments().then(setS).catch(() => setS(null))
  }, [])
  if (!s) return null
  const probe = (p: ExperimentsSummary['E1']['repair']['probes']) =>
    (['7', '30'] as const)
      .map((d) => (p[d].answered ? `${d}-day ${fmt(p[d].right)}/${fmt(p[d].answered)}` : null))
      .filter(Boolean)
      .join(', ') || 'no checks yet'
  const words = (n: number) => `${fmt(n)} ${n === 1 ? 'word' : 'words'}`
  const rows = [
    ['Repaired gloss (E1)', `${words(s.E1.repair.words)} · ${probe(s.E1.repair.probes)} · ${fmt(s.E1.repair.lapses_after)} lapses`,
      `${words(s.E1.control.words)} · ${probe(s.E1.control.probes)} · ${fmt(s.E1.control.lapses_after)} lapses`],
    ['Typed recall (E2)', `${words(s.E2.recall.words)} · ${probe(s.E2.recall.probes)}`,
      `${words(s.E2.control.words)} · ${probe(s.E2.control.probes)}`],
  ]
  return (
    <section className="mt-8">
      <h3 className="text-sm font-bold tracking-tight">Experiments</h3>
      <dl className="border-rule mt-3 border-t">
        {rows.map(([name, treated, control]) => (
          <div key={name} className="border-rule grid gap-x-4 gap-y-1 border-b py-2.5 text-sm sm:grid-cols-[12rem_1fr_1fr]">
            <dt className="font-semibold">{name}</dt>
            <dd className="tnum">With: {treated}</dd>
            <dd className="tnum text-ink-soft">Without: {control}</dd>
          </div>
        ))}
      </dl>
    </section>
  )
}

/* Lesson 06: evidence over sensation (Vision P4), drawn.
   Chart grammar per the dataviz method: one series per chart (cobalt, no
   legends), thin marks with rounded data-ends, hairline grid, text in ink
   tokens, hover tooltips, honest gaps where data is missing. */
export default function StatsPage() {
  const [stats, setStats] = useState<Stats | null>(null)
  const [error, setError] = useState(false)

  function load() {
    api.stats().then(setStats).catch(() => setError(true))
  }
  useEffect(load, [])

  if (error)
    return (
      <div className="mx-auto max-w-2xl px-6 pt-20 text-center">
        <ErrorLine
          onRetry={() => {
            setError(false)
            load()
          }}
        >
          Stats could not be opened. Is the local server running?
        </ErrorLine>
      </div>
    )

  return (
    <Page width="evidence">
      <PageHeader
        title="Stats"
        meta={
          stats && (
            <span className="font-book text-sm">
              Working level{' '}
              <span className="text-cobalt-deep font-semibold">{stats.recommendation.level}</span>
            </span>
          )
        }
      />

      {!stats ? (
        <RuledSkeleton lines={3} />
      ) : (
        <>
          {/* The ledger of facts */}
          <dl className="border-rule tnum mt-8 grid grid-cols-2 border-t sm:grid-cols-5">
            <Fact k="Words known" v={fmt(stats.totals.words_known)} />
            <Fact k="Mastered" v={fmt(stats.totals.mastered)} />
            <Fact k="Reviews all time" v={fmt(stats.totals.reviews_all_time)} />
            <Fact k="Texts read" v={fmt(stats.totals.texts_read)} />
            <Fact k="Streak" v={`${fmt(stats.totals.streak_days)} d`} />
          </dl>

          <CheckInLine />
          <ExperimentsLines />

          {/* What the level is actually read from (ADR-008): four sources,
              each with its sample. A gap here is stated, never guessed. */}
          <section className="mt-10">
            <div className="flex flex-wrap items-baseline justify-between gap-x-6">
              <h3 className="text-sm font-bold tracking-tight">
                What your level is read from
              </h3>
              <p className="text-ghost text-xs">last {stats.evidence.window_days} days</p>
            </div>
            <p className="font-book text-ink-soft mt-1 max-w-[68ch] text-sm">
              {stats.recommendation.reason}.
            </p>
            <dl className="border-rule mt-3 border-t">
              {(['recall', 'comprehension', 'controlled', 'production'] as const).map(
                (key) => {
                  const e = stats.evidence[key]
                  return (
                    <div
                      key={key}
                      className="border-rule grid grid-cols-[1fr_auto] items-baseline gap-x-4 gap-y-1 border-b py-2.5 sm:flex"
                    >
                      <dt className="text-ghost order-first text-xs font-semibold tracking-label uppercase sm:order-none sm:w-36 sm:shrink-0">
                        {e.label}
                      </dt>
                      <dd className="font-book text-ink min-w-0 flex-1 text-sm">
                        {e.display ?? <span className="text-ghost">no data yet</span>}
                      </dd>
                      <dd className="tnum text-ghost shrink-0 text-xs">
                        {fmt(e.n)} {e.unit}
                      </dd>
                      <dd
                        className={`order-first shrink-0 text-xs font-semibold tracking-label uppercase sm:order-none ${
                          e.signal === 'stretch'
                            ? 'text-cobalt-deep'
                            : e.signal === 'consolidate'
                              ? 'text-correction'
                              : 'text-ghost'
                        }`}
                      >
                        {e.signal === 'stretch'
                          ? 'stretch'
                          : e.signal === 'consolidate'
                            ? 'consolidate'
                            : e.signal === 'hold'
                              ? 'at level'
                              : 'not enough'}
                      </dd>
                    </div>
                  )
                },
              )}
            </dl>
            <p className="font-book text-ghost mt-2 text-sm italic">
              A day without writing is not a blind day: recall, comprehension and
              practice count too.
            </p>
          </section>

          <Chart title="Reviews per day" sub="last 30 days · Anki + in-app">
            <Columns
              data={stats.daily.map((d) => ({ label: d.date.slice(5), value: d.reviews }))}
            />
          </Chart>

          <Chart title="Vocabulary growth" sub="words met, cumulative · last 12 weeks">
            <TrendLine
              data={stats.weekly.map((w) => ({ label: w.week_start.slice(5), value: w.cumulative }))}
              format={(v) => fmt(Math.round(v))}
            />
          </Chart>

          <Chart
            title="Retention"
            sub="share of reviews recalled · weekly · gaps are weeks without reviews"
          >
            <TrendLine
              data={stats.weekly.map((w) => ({
                label: w.week_start.slice(5),
                value: w.retention != null ? w.retention * 100 : null,
              }))}
              domain={[50, 100]}
              format={(v) => `${Math.round(v)}%`}
            />
          </Chart>

          {/* The bill for spreading the backlog (ADR-009 D4). Three numbers
              do not want a bar chart — they want the same ruled rows the
              evidence table uses, each carrying its own sample. */}
          <section className="mt-10">
            <div className="flex flex-wrap items-baseline justify-between gap-x-6">
              <h3 className="text-sm font-bold tracking-tight">
                What answering late costs you
              </h3>
              <p className="text-ghost text-xs">in-app reviews · last 90 days</p>
            </div>
            <p className="font-book text-ink-soft mt-1 max-w-[68ch] text-sm">
              Spreading a backlog delays reviews, and a delayed card is recalled worse.
              This is that price, measured on your own cards rather than assumed.{' '}
              {stats.lateness.spreads.times === 0
                ? `Nothing has been spread in the last ${stats.lateness.spreads.window_days} days,
                   so any lateness here is simply days you did not study.`
                : `${fmt(stats.lateness.spreads.cards)} cards were rescheduled over
                   ${fmt(stats.lateness.spreads.times)} day${
                     stats.lateness.spreads.times === 1 ? '' : 's'
                   } in the last ${stats.lateness.spreads.window_days}.`}
            </p>
            <dl className="border-rule mt-3 border-t">
              {stats.lateness.by_bucket.map((b) => (
                <div
                  key={b.label}
                  className="border-rule grid grid-cols-[1fr_auto] items-baseline gap-x-4 gap-y-1 border-b py-2.5 sm:flex"
                >
                  <dt className="text-ghost col-span-2 text-xs font-semibold tracking-label uppercase sm:w-36 sm:shrink-0">
                    {b.label}
                  </dt>
                  <dd className="font-book text-ink min-w-0 flex-1 text-sm">
                    {b.recall != null ? (
                      `${Math.round(b.recall * 100)}% recalled`
                    ) : (
                      <span className="text-ghost">
                        {b.reviews === 0 ? 'none yet' : 'not enough to say'}
                      </span>
                    )}
                  </dd>
                  <dd className="tnum text-ghost shrink-0 text-xs">
                    {fmt(b.reviews)} review{b.reviews === 1 ? '' : 's'}
                  </dd>
                </div>
              ))}
            </dl>
            <p className="font-book text-ghost mt-2 text-sm italic">
              {stats.lateness.summary.enough && stats.lateness.summary.avg_days_late != null
                ? `On average you answer ${stats.lateness.summary.avg_days_late} days after a card
                   falls due; the worst was ${stats.lateness.summary.worst_days_late}.`
                : `A share needs ${stats.lateness.min_sample} reviews in its band before it means
                   anything — until then these rows stay blank rather than guess.`}
            </p>
          </section>

          <Chart
            title="Days late per review"
            sub="weekly average · gaps are weeks without in-app reviews"
          >
            <TrendLine
              data={stats.lateness.weekly.map((w) => ({
                label: w.week_start.slice(5),
                value: w.avg_days_late,
              }))}
              format={(v) => `${v.toFixed(1)} d`}
            />
          </Chart>

          <Chart title="Reading minutes" sub="last 30 days">
            <Columns
              data={stats.daily.map((d) => ({ label: d.date.slice(5), value: d.reading_minutes }))}
              format={(v) => `${v} min`}
            />
          </Chart>

          <Chart title="Speaking minutes" sub="last 30 days">
            <Columns
              data={stats.daily.map((d) => ({ label: d.date.slice(5), value: d.speaking_minutes }))}
              format={(v) => `${v} min`}
            />
          </Chart>

          <p className="font-book text-ghost mt-8 text-sm italic">
            {stats.errors_14d.enough_data && stats.errors_14d.errors_per_100 != null
              ? `Writing accuracy: ${stats.errors_14d.errors_per_100} errors per 100 words over the last two weeks.`
              : 'Writing accuracy: not enough production data in the last two weeks to state a number.'}
          </p>
        </>
      )}
    </Page>
  )
}

function Fact({ k, v }: { k: string; v: string }) {
  return (
    <div className="border-rule border-b py-4 pr-4">
      <dt className="text-ghost text-xs font-semibold tracking-label uppercase">{k}</dt>
      <dd className="text-ink mt-1 text-xl font-semibold tracking-tight">{v}</dd>
    </div>
  )
}

function Chart({ title, sub, children }: { title: string; sub: string; children: React.ReactNode }) {
  return (
    <section className="mt-10">
      <div className="flex flex-wrap items-baseline justify-between gap-x-6">
        <h3 className="text-sm font-bold tracking-tight">{title}</h3>
        <p className="text-ghost text-xs">{sub}</p>
      </div>
      <div className="mt-3">{children}</div>
    </section>
  )
}

const W = 640
const H = 120
const PAD = { top: 8, right: 4, bottom: 18, left: 30 }

interface Point {
  label: string
  value: number | null
}

function useTip() {
  const [tip, setTip] = useState<{ x: number; text: string } | null>(null)
  return { tip, setTip }
}

function Tip({ tip }: { tip: { x: number; text: string } | null }) {
  if (!tip) return null
  return (
    <div
      className="border-rule-strong text-ink pointer-events-none absolute -top-1 z-10 -translate-x-1/2 rounded-sm border bg-surface px-2 py-1 text-xs font-semibold whitespace-nowrap shadow-tip"
      style={{ left: `${(tip.x / W) * 100}%` }}
    >
      {tip.text}
    </div>
  )
}

function yTicks(max: number, min = 0): number[] {
  const span = max - min
  const step = span > 200 ? 100 : span > 80 ? 50 : span > 40 ? 20 : span > 12 ? 10 : span > 4 ? 5 : 1
  const out: number[] = []
  for (let v = Math.ceil(min / step) * step; v <= max; v += step) out.push(v)
  return out.slice(0, 5)
}

function Columns({ data, format = (v: number) => fmt(v) }: { data: Point[]; format?: (v: number) => string }) {
  const { tip, setTip } = useTip()
  const values = data.map((d) => d.value ?? 0)
  const max = Math.max(4, ...values)
  const iw = W - PAD.left - PAD.right
  const ih = H - PAD.top - PAD.bottom
  const bw = Math.max(2, iw / data.length - 2)
  const y = (v: number) => PAD.top + ih * (1 - v / max)

  return (
    <div className="relative">
      <Tip tip={tip} />
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label="Column chart">
        {yTicks(max).map((t) => (
          <g key={t}>
            <line x1={PAD.left} x2={W - PAD.right} y1={y(t)} y2={y(t)} stroke="var(--color-rule)" strokeWidth="1" />
            <text x={PAD.left - 6} y={y(t) + 3} textAnchor="end" fontSize="12" fill="var(--color-ghost)" className="tnum">
              {t}
            </text>
          </g>
        ))}
        {data.map((d, i) => {
          const x = PAD.left + (iw / data.length) * i + 1
          const v = d.value ?? 0
          const h = Math.max(v > 0 ? 2 : 0, ih * (v / max))
          return (
            <g key={i}>
              <rect
                x={x}
                y={y(0) - h}
                width={bw}
                height={h}
                rx={Math.min(2, bw / 2)}
                fill="var(--color-cobalt)"
                opacity={tip && tip.x !== x + bw / 2 ? 0.55 : 1}
              />
              <rect
                x={x - 1}
                y={PAD.top}
                width={bw + 2}
                height={ih}
                fill="transparent"
                onMouseEnter={() => setTip({ x: x + bw / 2, text: `${d.label} · ${format(v)}` })}
                onMouseLeave={() => setTip(null)}
              />
            </g>
          )
        })}
        <line x1={PAD.left} x2={W - PAD.right} y1={y(0)} y2={y(0)} stroke="var(--color-rule-strong)" strokeWidth="1" />
        <text x={PAD.left} y={H - 4} fontSize="12" fill="var(--color-ghost)">{data[0]?.label}</text>
        <text x={W - PAD.right} y={H - 4} textAnchor="end" fontSize="12" fill="var(--color-ghost)">
          {data[data.length - 1]?.label}
        </text>
      </svg>
    </div>
  )
}

function TrendLine({
  data,
  domain,
  format = (v: number) => fmt(Math.round(v)),
}: {
  data: Point[]
  domain?: [number, number]
  format?: (v: number) => string
}) {
  const { tip, setTip } = useTip()
  const present = data.filter((d): d is { label: string; value: number } => d.value != null)
  const values = present.map((d) => d.value)
  const min = domain?.[0] ?? 0
  const max = domain?.[1] ?? Math.max(4, ...values)
  const iw = W - PAD.left - PAD.right
  const ih = H - PAD.top - PAD.bottom
  const x = (i: number) => PAD.left + (iw / Math.max(1, data.length - 1)) * i
  const y = (v: number) => PAD.top + ih * (1 - (v - min) / (max - min))

  const path = data
    .map((d, i) => (d.value == null ? null : `${x(i)},${y(d.value)}`))
    .reduce<string>((acc, p) => {
      if (p == null) return acc + '|'
      const parts = acc.split('|')
      const last = parts[parts.length - 1]
      parts[parts.length - 1] = last ? `${last} L${p}` : `M${p}`
      return parts.join('|')
    }, '')
    .split('|')
    .filter(Boolean)
    .join(' ')

  return (
    <div className="relative">
      <Tip tip={tip} />
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label="Trend line chart">
        {yTicks(max, min).map((t) => (
          <g key={t}>
            <line x1={PAD.left} x2={W - PAD.right} y1={y(t)} y2={y(t)} stroke="var(--color-rule)" strokeWidth="1" />
            <text x={PAD.left - 6} y={y(t) + 3} textAnchor="end" fontSize="12" fill="var(--color-ghost)" className="tnum">
              {format(t)}
            </text>
          </g>
        ))}
        <path d={path} fill="none" stroke="var(--color-cobalt)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
        {data.map((d, i) =>
          d.value == null ? null : (
            <g key={i}>
              <circle
                cx={x(i)}
                cy={y(d.value)}
                r={tip?.x === x(i) ? 4 : 2.5}
                fill="var(--color-cobalt)"
                stroke="var(--color-paper)"
                strokeWidth="2"
              />
              <rect
                x={x(i) - iw / data.length / 2}
                y={PAD.top}
                width={iw / data.length}
                height={ih}
                fill="transparent"
                onMouseEnter={() => setTip({ x: x(i), text: `${d.label} · ${format(d.value!)}` })}
                onMouseLeave={() => setTip(null)}
              />
            </g>
          ),
        )}
        <text x={PAD.left} y={H - 4} fontSize="12" fill="var(--color-ghost)">{data[0]?.label}</text>
        <text x={W - PAD.right} y={H - 4} textAnchor="end" fontSize="12" fill="var(--color-ghost)">
          {data[data.length - 1]?.label}
        </text>
      </svg>
    </div>
  )
}
