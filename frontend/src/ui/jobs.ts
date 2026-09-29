import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../api'
import type { Job, JobKind } from '../api'

/* The local model takes 15–80 s on this laptop, so every wait in the app is
   long enough to walk away from. Two things follow, and neither was true
   before M23: the wait has to survive leaving the screen, and it has to say
   how long it has been going. */

const POLL_MS = 1500

/** Seconds since `since`, ticking once a second. Null pauses the clock. */
export function useElapsed(since: number | null): number {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    if (since == null) return
    setNow(Date.now())
    const t = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(t)
  }, [since])
  return since == null ? 0 : Math.max(0, Math.round((now - since) / 1000))
}

/** "0:42" — the shape of a stopwatch, not a percentage we cannot honour. */
export function clock(seconds: number): string {
  const m = Math.floor(seconds / 60)
  const s = seconds % 60
  return `${m}:${String(s).padStart(2, '0')}`
}

/* Reattach to work already in flight. On mount it asks the server which jobs
   of these kinds are queued or running and follows the newest one, so coming
   back to a screen shows the wait instead of an empty page. */
export function useJobWatch(kinds: JobKind[], onDone?: (job: Job) => void) {
  const [job, setJob] = useState<Job | null>(null)
  const [pending, setPending] = useState(0)
  const kindKey = kinds.join(',')
  const done = useRef(onDone)
  done.current = onDone

  const follow = useCallback((j: Job) => setJob(j), [])

  useEffect(() => {
    const wanted = new Set(kindKey.split(',') as JobKind[])
    let live = true
    let timer: ReturnType<typeof setTimeout>

    async function tick() {
      try {
        const current = job
        if (current && (current.status === 'queued' || current.status === 'running')) {
          const fresh = await api.job(current.id)
          if (!live) return
          setPending(fresh.pending ?? 0)
          setJob(fresh)
          if (fresh.status === 'done' || fresh.status === 'failed') {
            done.current?.(fresh)
            return
          }
        } else if (!current) {
          const { jobs, pending: p } = await api.jobs()
          if (!live) return
          setPending(p)
          const mine = jobs.find(
            (j) => wanted.has(j.kind) && (j.status === 'queued' || j.status === 'running'),
          )
          if (mine) setJob(mine)
          else return /* nothing in flight: stop asking */
        }
      } catch {
        /* The server went away; the screen's own error path owns that. */
        return
      }
      if (live) timer = setTimeout(tick, POLL_MS)
    }

    timer = setTimeout(tick, job ? POLL_MS : 0)
    return () => {
      live = false
      clearTimeout(timer)
    }
  }, [kindKey, job])

  return { job, pending, follow, clear: () => setJob(null) }
}

/* What the coach says while it works. The queue line is the honest part:
   one inference at a time is why the laptop stays usable. */
export function queueNote(job: Job | null, pending: number): string | undefined {
  if (!job) return undefined
  if (job.status === 'queued') {
    const ahead = Math.max(0, (job.pending ?? pending) - 1)
    return ahead > 0
      ? `In line behind other work — ${ahead} ahead. One at a time keeps the laptop cool.`
      : 'Next in line.'
  }
  return undefined
}

/* Errors arrive as `AIUnavailable: …` or a raw exception string. Name the
   problem in the reader's language and keep the original out of the page. */
export function describeError(raw: string | null | undefined, fallback: string): string {
  const text = raw ?? ''
  if (/no credentials|ANTHROPIC_API_KEY/i.test(text))
    return 'The cloud coach has no key, so nothing can be written right now.'
  if (/connection|refused|10061|Max retries|not running/i.test(text))
    return 'Ollama is not running, so the coach cannot write. Start it and try again.'
  if (/model.*(not found|missing)|pull/i.test(text))
    return 'The local model is not downloaded yet, so the coach cannot write.'
  if (/timeout|timed out/i.test(text))
    return 'The coach took too long and gave up. Trying again usually works.'
  return fallback
}
