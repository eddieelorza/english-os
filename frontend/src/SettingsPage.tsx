import { useEffect, useState } from 'react'
import { api } from './api'
import type { AIStatus, ProviderSettings, SettingsField, SettingsGroup, VoiceTest } from './api'
import { Button, ErrorLine, Page, PageHeader, RuledSkeleton, Section, describeError } from './ui'

const inputClass = 'border-rule bg-paper text-ink w-full rounded-sm border px-3 py-2 text-sm'

function errorMessage(error: unknown) {
  const message = error instanceof Error ? error.message : 'Could not load or save settings.'
  return describeError(message, message)
}

function AIState({ revision }: { revision: number }) {
  const [status, setStatus] = useState<AIStatus | null>(null)
  const [error, setError] = useState('')
  useEffect(() => {
    let active = true
    api.aiStatus().then((next) => {
      if (active) { setStatus(next); setError('') }
    }).catch((reason: unknown) => { if (active) setError(errorMessage(reason)) })
    return () => { active = false }
  }, [revision])
  if (error) return <ErrorLine>{error}</ErrorLine>
  if (!status) return <p role="status" className="text-ghost mb-5 text-sm">Checking AI status…</p>
  return (
    <dl className="border-rule mb-6 grid gap-2 border-b pb-5 text-sm sm:grid-cols-2" aria-live="polite">
      <div><dt className="text-ghost">Active provider</dt><dd>{status.provider || 'None'}</dd></div>
      <div><dt className="text-ghost">Model</dt><dd className="break-words">{status.model || 'None'}</dd></div>
      <div><dt className="text-ghost">Anthropic</dt><dd>{status.anthropic_available ? 'Available' : 'Unavailable'}</dd></div>
      <div><dt className="text-ghost">Ollama</dt><dd>{status.ollama_running ? 'Running' : 'Not running'}</dd></div>
    </dl>
  )
}

function SecretField({ field, value, onChange }: {
  field: Extract<SettingsField, { kind: 'secret' }>
  value: string | null | undefined
  onChange: (value: string | null | undefined) => void
}) {
  const replacing = typeof value === 'string'
  return (
    <div className="space-y-2">
      <p className="text-ink-soft text-sm" role="status">
        {value === null ? 'Will be removed on save' : field.set ? `Set · ${field.hint || '…'}` : 'Not set'}
      </p>
      {replacing && <input id={field.key} aria-label={field.label} aria-describedby={`${field.key}-help`}
        type="password" autoComplete="off" maxLength={300} value={value}
        onChange={(event) => onChange(event.target.value)} className={inputClass} />}
      <div className="flex gap-4">
        {value !== undefined
          ? <Button type="button" variant="text" onClick={() => onChange(undefined)}>Cancel</Button>
          : <Button type="button" variant="text" tone="cobalt" onClick={() => onChange('')}>Replace</Button>}
        {field.set && value !== null && <Button type="button" variant="text" tone="correction"
          onClick={() => onChange(null)}>Remove</Button>}
      </div>
    </div>
  )
}

function GroupForm({ group }: { group: SettingsGroup }) {
  const [saved, setSaved] = useState(group)
  const [changes, setChanges] = useState<Record<string, string | null>>({})
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const [revision, setRevision] = useState(0)
  const [testing, setTesting] = useState(false)
  const [test, setTest] = useState<VoiceTest | null>(null)
  const dirty = Object.keys(changes).length > 0
  const emptyReplacement = saved.fields.some((field) => field.kind === 'secret' && changes[field.key] === '')

  function change(field: SettingsField, value: string | null | undefined) {
    setChanges((previous) => {
      const next = { ...previous }
      if (value === undefined || (field.kind !== 'secret' && (value ?? '') === field.value)) delete next[field.key]
      else next[field.key] = value
      return next
    })
    setMessage('')
    setError('')
    setTest(null)
  }

  async function save() {
    setSaving(true)
    setError('')
    setMessage('')
    try {
      const result = await api.saveSettings(changes)
      setSaved(result.groups.find((item) => item.name === group.name)!)
      setChanges({})
      setTest(null)
      setMessage('Saved. Changes are active now.')
      setRevision((previous) => previous + 1)
    } catch (reason) { setError(errorMessage(reason)) }
    finally { setSaving(false) }
  }

  async function testVoice() {
    setTesting(true)
    setTest(null)
    try { setTest(await api.testVoice()) }
    catch (reason) { setTest({ ok: false, error: errorMessage(reason) }) }
    finally { setTesting(false) }
  }

  return (
    <Section label={group.name}>
      {group.name === 'AI' && <AIState revision={revision} />}
      <form aria-label={`${group.name} settings`} onSubmit={(event) => { event.preventDefault(); void save() }}>
        <fieldset disabled={saving || testing} className="min-w-0 space-y-5">
          {saved.fields.map((field) => (
            <div key={field.key}>
              {field.kind === 'secret'
                ? <p className="mb-1.5 text-sm font-semibold">{field.label}</p>
                : <label htmlFor={field.key} className="mb-1.5 block text-sm font-semibold">{field.label}</label>}
              {field.kind === 'secret'
                ? <SecretField field={field} value={changes[field.key]} onChange={(value) => change(field, value)} />
                : field.kind === 'select'
                  ? <select id={field.key} value={changes[field.key] ?? field.value} className={inputClass}
                      aria-describedby={`${field.key}-help`} onChange={(event) => change(field, event.target.value)}>
                      <option value="">Default (unset)</option>
                      {field.options.map((option) => <option key={option} value={option}>{option}</option>)}
                    </select>
                  : <input id={field.key} type={field.kind === 'number' ? 'number' : 'text'}
                      min={field.kind === 'number' ? 0 : undefined} step={field.kind === 'number' ? 'any' : undefined}
                      maxLength={300} value={changes[field.key] ?? field.value} className={inputClass}
                      aria-describedby={`${field.key}-help`} onChange={(event) => change(field, event.target.value)} />}
              <p id={`${field.key}-help`} className="text-ghost mt-1.5 text-xs">{field.help}</p>
            </div>
          ))}
          <div className="flex flex-wrap items-center gap-3">
            <Button type="submit" disabled={!dirty || emptyReplacement}>{saving ? 'Saving…' : 'Save'}</Button>
            {group.name === 'Voice' && <Button type="button" variant="secondary" disabled={dirty}
              onClick={() => void testVoice()}>{testing ? 'Testing…' : 'Test voice'}</Button>}
          </div>
        </fieldset>
        {group.name === 'Voice' && <p className="text-ghost mt-3 text-xs">
          {dirty ? 'Save your changes before testing.' : 'Tests the saved voice without using credits.'}
        </p>}
        {message && <p role="status" className="text-cobalt-deep mt-3 text-sm">{message}</p>}
        {error && <ErrorLine>{error}</ErrorLine>}
        {test && (test.ok
          ? <p role="status" className="text-cobalt-deep mt-3 text-sm">Voice ready: {test.voice_name}</p>
          : <ErrorLine>{test.error}</ErrorLine>)}
      </form>
    </Section>
  )
}

export default function SettingsPage() {
  const [settings, setSettings] = useState<ProviderSettings | null>(null)
  const [error, setError] = useState('')
  const [attempt, setAttempt] = useState(0)
  useEffect(() => {
    let active = true
    api.settings().then((result) => {
      if (active) { setSettings(result); setError('') }
    }).catch((reason: unknown) => { if (active) setError(errorMessage(reason)) })
    return () => { active = false }
  }, [attempt])
  return (
    <Page>
      <PageHeader title="Settings" subtitle="Configure your AI providers, voice and spending limits." />
      {error && <ErrorLine onRetry={() => setAttempt((previous) => previous + 1)}>{error}</ErrorLine>}
      {!settings && !error && <RuledSkeleton />}
      {settings?.groups.map((group) => <GroupForm key={group.name} group={group} />)}
    </Page>
  )
}
