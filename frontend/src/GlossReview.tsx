import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from './api'
import type { GlossProposal, GlossQueue } from './api'
import {
  Section, Button, ErrorLine, Waiting, Empty, RuledSkeleton,
  useJobWatch, describeError, queueNote, fmt,
} from './ui'

export default function GlossReview() {
  const [queue, setQueue] = useState<GlossQueue | null>(null)
  const [index, setIndex] = useState(0)
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [jobError, setJobError] = useState<string | null>(null)
  const [decisionError, setDecisionError] = useState<string | null>(null)
  const [undoError, setUndoError] = useState<string | null>(null)
  const [starting, setStarting] = useState(false)
  const [saving, setSaving] = useState(false)
  const [editing, setEditing] = useState(false)
  const [gloss, setGloss] = useState('')
  const [definition, setDefinition] = useState('')
  const [accepted, setAccepted] = useState<GlossProposal | null>(null)
  const [announcement, setAnnouncement] = useState('')
  const live = useRef(true)
  const requestId = useRef(0)
  const locked = useRef(false)
  const focusNext = useRef(false)
  const heading = useRef<HTMLHeadingElement>(null)
  const proposalArea = useRef<HTMLDivElement>(null)
  const glossInput = useRef<HTMLInputElement>(null)

  const load = useCallback(async () => {
    const id = ++requestId.current
    setLoading(true)
    setLoadError(null)
    try {
      const next = await api.glossQueue()
      if (!live.current || id !== requestId.current) return
      setQueue(next)
      setIndex(0)
    } catch {
      if (!live.current || id !== requestId.current) return
      setLoadError('The gloss review queue could not be read. Try again.')
    } finally {
      if (live.current && id === requestId.current) setLoading(false)
    }
  }, [])

  useEffect(() => {
    live.current = true
    void load()
    return () => {
      live.current = false
    }
  }, [load])

  const { job, pending, follow } = useJobWatch(['vocab_audit'], (finished) => {
    if (finished.status === 'failed') {
      setJobError(describeError(finished.error, 'The coach could not find fixes. Try again.'))
    }
    void load()
  })
  const generating = starting || job?.status === 'queued' || job?.status === 'running'
  const proposal = queue?.proposed[index]

  useEffect(() => {
    if (!loading && focusNext.current && heading.current) {
      heading.current.focus()
      focusNext.current = false
    }
  }, [proposal?.id, loading])

  useEffect(() => {
    if (editing) glossInput.current?.focus()
  }, [editing])

  async function findFixes() {
    if (locked.current || generating) return
    locked.current = true
    setStarting(true)
    setJobError(null)
    try {
      const created = await api.proposeGlosses({ limit: 20 })
      if (!live.current) return
      follow(created)
      if (created.status === 'done' || created.status === 'failed') {
        if (created.status === 'failed') {
          setJobError(describeError(created.error, 'The coach could not find fixes. Try again.'))
        }
        void load()
      }
    } catch (error) {
      if (live.current) {
        setJobError(describeError(error instanceof Error ? error.message : null,
          'The coach could not start finding fixes. Try again.'))
      }
    } finally {
      locked.current = false
      if (live.current) setStarting(false)
    }
  }

  const openEdit = useCallback(() => {
    if (!proposal || locked.current || loading) return
    setGloss(proposal.gloss_es)
    setDefinition(proposal.definition_en ?? '')
    setDecisionError(null)
    setEditing(true)
  }, [proposal, loading])

  const decide = useCallback(async (action: 'accept' | 'reject', edited = false) => {
    if (!proposal || locked.current || loading) return
    locked.current = true
    setSaving(true)
    setDecisionError(null)
    try {
      await api.decideGloss(proposal.id, {
        action,
        ...(edited ? { gloss_es: gloss, definition_en: definition } : {}),
      })
      if (!live.current) return
      setAccepted(action === 'accept' ? proposal : null)
      setUndoError(null)
      setAnnouncement(`${action === 'accept' ? 'Accepted' : 'Rejected'} “${proposal.word}”.`)
      setEditing(false)
      focusNext.current = true
      setIndex(index + 1)
      if (index + 1 === queue!.proposed.length) await load()
    } catch (error) {
      if (live.current) {
        setDecisionError(error instanceof Error ? error.message : 'The decision could not be saved. Try again.')
      }
    } finally {
      locked.current = false
      if (live.current) setSaving(false)
    }
  }, [proposal, loading, gloss, definition, index, queue, load])

  async function undo() {
    if (!accepted || locked.current || loading) return
    locked.current = true
    setSaving(true)
    setUndoError(null)
    try {
      await api.decideGloss(accepted.id, { action: 'revert' })
      if (!live.current) return
      setAnnouncement(`Reverted “${accepted.word}”.`)
      setAccepted(null)
      setEditing(false)
      setDecisionError(null)
      focusNext.current = true
      await load()
    } catch (error) {
      if (live.current) {
        setUndoError(error instanceof Error ? error.message : 'The gloss could not be reverted. Try again.')
      }
    } finally {
      locked.current = false
      if (live.current) setSaving(false)
    }
  }

  useEffect(() => {
    if (!proposal || loading || loadError || editing || saving) return
    function onKey(event: KeyboardEvent) {
      if (event.altKey || event.ctrlKey || event.metaKey || event.shiftKey || event.repeat || event.isComposing) return
      const target = event.target
      if (target instanceof HTMLElement && (target.closest('input, textarea, select') || target.isContentEditable)) return
      const rect = proposalArea.current?.getBoundingClientRect()
      if (!rect || rect.bottom <= 0 || rect.top >= window.innerHeight || document.hidden) return
      const key = event.key.toLowerCase()
      if (!['a', 'r', 'e'].includes(key)) return
      event.preventDefault()
      if (key === 'e') openEdit()
      else void decide(key === 'a' ? 'accept' : 'reject')
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [proposal, loading, loadError, editing, saving, decide, openEdit])

  if (!loading && !loadError && !generating && !jobError && !proposal && !queue?.candidates && !accepted) return null

  const startedAt = job ? Date.parse(job.started_at ?? job.created_at) : NaN

  return (
    <Section
      label="Glosses to review"
      className="font-ui"
      right={!loading && !loadError && proposal && <span className="tnum">{fmt(index + 1)} of {fmt(queue!.proposed.length)}</span>}
    >
      <p role="status" aria-atomic="true" className="text-ghost text-sm">{announcement}</p>
      {accepted && (
        <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1">
          <span className="text-ghost text-sm">Accepted <span className="font-book">{accepted.word}</span>.</span>
          <Button variant="text" tone="cobalt" onClick={undo} disabled={saving || loading || starting}>Undo</Button>
        </div>
      )}
      {undoError && <ErrorLine>{undoError}</ErrorLine>}
      {loading && <div role="status" aria-label="Loading glosses" aria-busy="true"><RuledSkeleton lines={3} /></div>}
      {loadError && <ErrorLine onRetry={load}>{loadError}</ErrorLine>}
      {generating && (
        <Waiting note={queueNote(job, pending)} since={Number.isFinite(startedAt) ? startedAt : null}>
          {job?.status === 'running' ? 'The coach is finding fixes…' : 'Waiting to find fixes…'}
        </Waiting>
      )}
      {jobError && !generating && <ErrorLine onRetry={findFixes}>{jobError}</ErrorLine>}

      {!loading && !loadError && !proposal && queue && (
        queue.candidates > 0 ? (
          <div className="mt-4 flex flex-wrap items-center gap-4">
            <p className="font-book text-ink-soft">{fmt(queue.candidates)} cards have a gloss that does not match their example.</p>
            {!generating && !jobError && <Button variant="secondary" onClick={findFixes} disabled={saving}>Find fixes</Button>}
          </div>
        ) : accepted && <div role="status"><Empty>All reviewed.</Empty></div>
      )}

      {!loading && !loadError && proposal && (
        <div ref={proposalArea} className="mt-4 max-w-prose break-words">
          <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
            <h4 ref={heading} tabIndex={-1} className="font-book text-3xl font-semibold">{proposal.word}</h4>
            {proposal.pos && <span className="text-ghost text-sm">{proposal.pos}</span>}
          </div>
          {proposal.example_en && <p className="font-book mt-4 text-lg">{proposal.example_en}</p>}
          {proposal.example_es && <p lang="es" className="font-book text-cobalt-deep mt-2 text-lg">{proposal.example_es}</p>}
          <dl className="border-rule mt-6 space-y-4 border-t pt-4">
            <div>
              <dt className="text-ghost text-xs">On the card now</dt>
              <dd className="font-book mt-1 text-lg">
                {proposal.current_gloss == null ? <span className="font-ui text-ghost text-sm">nothing</span> : <span lang="es">{proposal.current_gloss}</span>}
              </dd>
            </div>
            <div>
              <dt className="text-ghost text-xs">Proposed</dt>
              <dd className="font-book mt-1 text-lg">
                <span lang="es" className="text-cobalt-deep">{proposal.gloss_es}</span>
                {proposal.definition_en && <p className="mt-1">{proposal.definition_en}</p>}
              </dd>
            </div>
          </dl>
          {proposal.note_es && <p lang="es" className="font-book text-ghost mt-4 text-base italic">{proposal.note_es}</p>}
          {proposal.second && (
            <p className="font-book text-ink-soft mt-4 text-base">
              <span className="font-ui text-sm">Also: </span>
              <span lang="es">{proposal.second.gloss_es}</span> — {proposal.second.example_en}
            </p>
          )}
          {editing ? (
            <form className="border-rule mt-6 space-y-4 border-t pt-4" onSubmit={(event) => { event.preventDefault(); void decide('accept', true) }}>
              <label className="block text-sm">
                Spanish gloss
                <input ref={glossInput} lang="es" value={gloss} onChange={(event) => setGloss(event.target.value)} disabled={saving}
                  className="font-book border-rule-strong mt-2 block w-full border-b bg-transparent py-2 text-lg" />
              </label>
              <label className="block text-sm">
                English definition
                <input value={definition} onChange={(event) => setDefinition(event.target.value)} disabled={saving}
                  className="font-book border-rule-strong mt-2 block w-full border-b bg-transparent py-2 text-lg" />
              </label>
              {decisionError && <ErrorLine>{decisionError}</ErrorLine>}
              <div className="flex flex-wrap items-center gap-4">
                <Button type="submit" disabled={saving}>Save and accept</Button>
                <Button type="button" variant="text" disabled={saving} onClick={() => { setEditing(false); setDecisionError(null); heading.current?.focus() }}>Cancel</Button>
              </div>
            </form>
          ) : (
            <>
              {decisionError && <ErrorLine>{decisionError}</ErrorLine>}
              <div className="mt-6 flex flex-wrap items-center gap-4">
                <Button onClick={() => void decide('accept')} disabled={saving || starting}>Accept</Button>
                <Button variant="secondary" onClick={openEdit} disabled={saving || starting}>Edit</Button>
                <Button variant="text" onClick={() => void decide('reject')} disabled={saving || starting}>Reject</Button>
              </div>
              <p className="text-ghost pointer-coarse:hidden mt-3 text-xs">Press A to accept, R to reject or E to edit.</p>
            </>
          )}
        </div>
      )}
    </Section>
  )
}
