import { NavLink, Navigate, Route, Routes, useLocation } from 'react-router-dom'
import { motion } from 'motion/react'
import { SLIDE } from './ui'
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

interface Lesson {
  n: string
  name: string
  path?: string
}

/* The course rail: modules as numbered lessons — the sequence is the course
   order (M-roadmap), so the numbers carry real information. */
/* Course order: the day (01) → the material you take in (02-04) → the drills
   (05-06) → what you produce (07-08) → the evidence (09). */
const LESSONS: Lesson[] = [
  { n: '01', name: 'Today', path: '/' },
  { n: '02', name: 'Vocabulary', path: '/vocabulary' },
  { n: '03', name: 'Reading', path: '/reading' },
  { n: '04', name: 'Podcast', path: '/podcast' },
  { n: '05', name: 'Review', path: '/review' },
  { n: '06', name: 'Practice', path: '/practice' },
  { n: '07', name: 'Writing', path: '/writing' },
  { n: '08', name: 'Speaking', path: '/speaking' },
  { n: '09', name: 'Shadowing', path: '/shadowing' },
  { n: '10', name: 'Stats', path: '/stats' },
]

export default function App() {
  const { pathname } = useLocation()
  return (
    <div className="min-h-screen lg:flex">
      {/* Cobalt spine — the workbook cover */}
      <aside className="bg-cobalt text-paper flex shrink-0 flex-row items-center justify-between gap-3 px-4 py-2.5 lg:min-h-screen lg:w-60 lg:flex-col lg:items-stretch lg:justify-start lg:px-0 lg:py-0">
        <header className="shrink-0 lg:border-paper/20 lg:border-b lg:px-7 lg:pt-10 lg:pb-8">
          <h1 className="text-lg leading-none font-extrabold tracking-tight whitespace-nowrap lg:text-2xl">
            English OS
          </h1>
          <p className="hidden text-[11px] font-semibold tracking-[0.28em] uppercase opacity-80 lg:mt-2 lg:block">
            The self-study method
          </p>
        </header>

        {/* Eight lessons no longer fit a narrow top bar: below lg the rail
            scrolls horizontally and drops the numbers. */}
        <nav
          aria-label="Course modules"
          className="min-w-0 flex-1 overflow-x-auto lg:overflow-visible lg:px-4 lg:py-6"
        >
          <ul className="flex gap-0.5 lg:flex-col lg:gap-1">
            {LESSONS.map((l) => (
              <li key={l.n} className="shrink-0">
                {l.path ? (
                  <NavLink
                    to={l.path}
                    end={l.path === '/'}
                    className={({ isActive }) =>
                      isActive
                        ? 'bg-paper text-cobalt-deep flex items-baseline gap-2 rounded-sm px-2.5 py-1.5 font-semibold lg:gap-3 lg:-mr-4 lg:rounded-r-none lg:px-3 lg:py-2.5'
                        : 'text-paper/80 hover:text-paper flex items-baseline gap-2 rounded-sm px-2.5 py-1.5 font-semibold transition-colors lg:gap-3 lg:px-3 lg:py-2.5'
                    }
                  >
                    <span className="tnum hidden text-[11px] opacity-70 lg:inline">{l.n}</span>
                    <span className="text-[13px] tracking-wide whitespace-nowrap lg:text-sm">
                      {l.name}
                    </span>
                  </NavLink>
                ) : (
                  <span
                    className="hidden items-baseline gap-3 px-3 py-2.5 opacity-45 lg:flex"
                    title="In preparation"
                  >
                    <span className="tnum text-[11px]">{l.n}</span>
                    <span className="text-sm tracking-wide">{l.name}</span>
                  </span>
                )}
              </li>
            ))}
          </ul>
        </nav>

        <footer className="hidden lg:border-paper/20 lg:block lg:border-t lg:px-7 lg:py-5">
          <p className="text-[11px] tracking-[0.2em] uppercase opacity-70">
            Course 2026 · A2 → C1
          </p>
        </footer>
      </aside>

      {/* The open page */}
      <main className="min-w-0 flex-1">
        {/* The arriving page slides in along its column (DESIGN rule 4). There
            is no exit animation on purpose: waiting for the old page to leave
            would make every navigation 320 ms slower in order to feel smoother. */}
        <motion.div
          key={pathname}
          initial={{ y: 8, opacity: 0 }}
          animate={{ y: 0, opacity: 1 }}
          transition={SLIDE}
        >
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
        </motion.div>
      </main>
    </div>
  )
}
