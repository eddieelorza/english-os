import { useCallback, useState } from 'react'
import { api } from './api'
import type { GuidedResult, WritingTask } from './api'
import GuidedWriting from './GuidedWriting'
import { GuidedSummary } from './WritingPage'
import SessionNext from './SessionNext'
import { ButtonLink, Empty, Page, PageHeader } from './ui'

export default function MicroWritingPage() {
  const [result, setResult] = useState<GuidedResult | null>(null)
  const [empty, setEmpty] = useState(false)

  // No words yet comes back as a task without steps: a quiet empty state.
  const load = useCallback(async (): Promise<WritingTask> => {
    const task = await api.writingMicro()
    if (!task.steps.length) {
      setEmpty(true)
      throw new Error('Nothing to write with yet.')
    }
    return task
  }, [])

  return (
    <Page width="study">
      <PageHeader title="Write" subtitle="Two sentences with the words you just recalled." />
      {result ? (
        <>
          <GuidedSummary result={result} />
          <SessionNext after="write" />
        </>
      ) : empty ? (
        <>
          <Empty hint="Recall a few words first.">Nothing to write with yet.</Empty>
          <ButtonLink to="/" variant="text" tone="cobalt" className="mt-4">
            Back to Today
          </ButtonLink>
        </>
      ) : (
        <GuidedWriting
          load={load}
          draftKey="writing.micro.v1"
          loadingLabel="Picking today's words…"
          onDone={setResult}
        />
      )}
    </Page>
  )
}
