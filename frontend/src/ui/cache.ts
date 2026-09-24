import { useEffect, useState } from 'react'

/* Stale-while-revalidate, the small version.

   Every page used to fetch from zero on every visit: Today → Stats → Today
   re-ran the request and re-showed the skeleton each time, so moving around
   felt like reloading. Here the last answer for a key is kept in memory: a
   page seeds its state with `peekCache`, so a return visit paints at once with
   what was known, and writes through with `primeCache` when the fresh answer
   lands.

   In memory on purpose — one user, one tab, and a reload should ask again. */

const store = new Map<string, unknown>()

/* For pages that keep their own state: seed it from the last visit and write
   through on every load. */
export function peekCache<T>(key: string): T | null {
  return (store.get(key) as T | undefined) ?? null
}

export function primeCache<T>(key: string, value: T) {
  store.set(key, value)
}

export function dropCache(prefix?: string) {
  if (!prefix) return store.clear()
  for (const k of [...store.keys()]) if (k.startsWith(prefix)) store.delete(k)
}

/* A skeleton that flashes for 40 ms is worse than none: it reads as a glitch.
   Returns true only once the wait has outlived `ms`. */
export function useDelayed(active: boolean, ms = 140) {
  const [shown, setShown] = useState(false)
  useEffect(() => {
    if (!active) return
    const t = setTimeout(() => setShown(true), ms)
    return () => {
      clearTimeout(t)
      setShown(false)
    }
  }, [active, ms])
  return shown && active
}
