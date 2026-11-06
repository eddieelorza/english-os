import { Navigate, Route, Routes, useLocation } from 'react-router-dom'
import { Shell } from './ui'
import TodayPage from './TodayPage'
import VocabularyPage from './VocabularyPage'
import ReadingPage from './ReadingPage'
import ReaderPage from './ReaderPage'
import ReviewPage from './ReviewPage'
import SpeakingPage from './SpeakingPage'
import ShadowingPage from './ShadowingPage'
import StatsPage from './StatsPage'
import PracticePage from './PracticePage'
import PodcastPage from './PodcastPage'
import WritingPage from './WritingPage'

export default function App() {
  const { pathname } = useLocation()
  return (
    <Shell>
      {/* Navigation is the most repeated thing in the app, so the arriving page
          only fades, and fast. There is no exit on purpose: waiting for the old
          page to leave would slow every navigation in order to feel smoother.
          In CSS, not Motion: a frame-driven fade leaves the page nearly invisible
          whenever the main thread is busy, which is exactly when a page arrives. */}
      <div key={pathname} className="fade-in">
        <Routes>
          <Route path="/" element={<TodayPage />} />
          <Route path="/vocabulary" element={<VocabularyPage />} />
          <Route path="/reading" element={<ReadingPage />} />
          <Route path="/reading/:id" element={<ReaderPage />} />
          <Route path="/review" element={<ReviewPage />} />
          <Route path="/podcast" element={<PodcastPage />} />
          <Route path="/practice" element={<PracticePage />} />
          <Route path="/writing" element={<WritingPage />} />
          <Route path="/speaking" element={<SpeakingPage />} />
          <Route path="/shadowing" element={<ShadowingPage />} />
          <Route path="/stats" element={<StatsPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </div>
    </Shell>
  )
}
