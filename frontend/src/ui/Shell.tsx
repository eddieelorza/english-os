import { useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { Link, NavLink, useLocation, useNavigationType } from 'react-router-dom'
import {
  BookOpen,
  CalendarDays,
  Layers,
  Library,
  Moon,
  PanelLeftClose,
  PanelLeftOpen,
  PenLine,
  Sun,
  SunMoon,
} from 'lucide-react'
import type { LucideIcon } from 'lucide-react'

/* The course, in the order a day runs: the day (01), the deck (02), what you
   take in (03-05), what you do with it (06-08), the record (09-10). The numbers
   carry that order, which is why the groups are the same five on every screen:
   the rail lists them, the phone's tab bar is them. */
const GROUPS: { tab: string; label?: string; icon: LucideIcon; lessons: Lesson[] }[] = [
  { tab: 'Today', icon: CalendarDays, lessons: [{ n: '01', name: 'Today', path: '/' }] },
  { tab: 'Review', icon: Layers, lessons: [{ n: '02', name: 'Review', path: '/review' }] },
  {
    tab: 'Read',
    label: 'Take in',
    icon: BookOpen,
    lessons: [
      { n: '03', name: 'Reading', path: '/reading' },
      { n: '04', name: 'Podcast', path: '/podcast' },
      { n: '05', name: 'Shadowing', path: '/shadowing' },
    ],
  },
  {
    tab: 'Practice',
    label: 'Put to use',
    icon: PenLine,
    lessons: [
      { n: '06', name: 'Practice', path: '/practice' },
      { n: '07', name: 'Writing', path: '/writing' },
      { n: '08', name: 'Speaking', path: '/speaking' },
    ],
  },
  {
    tab: 'More',
    label: 'Your record',
    icon: Library,
    lessons: [
      { n: '09', name: 'Vocabulary', path: '/vocabulary' },
      { n: '10', name: 'Stats', path: '/stats' },
    ],
  },
]

interface Lesson {
  n: string
  name: string
  path: string
}

const isIn = (pathname: string, path: string) =>
  path === '/' ? pathname === '/' : pathname === path || pathname.startsWith(`${path}/`)

/* Reading one text is inside a lesson, not a place on the map. */
const isDeep = (pathname: string) => /^\/reading\/.+/.test(pathname)
/* Drilling and reading want the page, so the rail folds to its numerals there. */
const isFocus = (pathname: string) => pathname === '/review' || isDeep(pathname)

function read(key: string) {
  try {
    return localStorage.getItem(key)
  } catch {
    return null
  }
}
function write(key: string, value: string) {
  try {
    localStorage.setItem(key, value)
  } catch {
    /* A private window keeps the choice for this page only. */
  }
}

type Theme = 'auto' | 'light' | 'dark'
const NEXT_THEME: Record<Theme, Theme> = { auto: 'light', light: 'dark', dark: 'auto' }
const THEME_FACE: Record<Theme, { word: string; icon: LucideIcon }> = {
  auto: { word: 'Auto', icon: SunMoon },
  light: { word: 'Day', icon: Sun },
  dark: { word: 'Night', icon: Moon },
}

/* index.html applies the same choice before first paint; this keeps it true
   afterwards, including when the system flips at dusk under "auto". */
function useTheme() {
  const [theme, setTheme] = useState<Theme>(() => {
    const saved = read('theme')
    return saved === 'light' || saved === 'dark' ? saved : 'auto'
  })
  useEffect(() => {
    const night = matchMedia('(prefers-color-scheme: dark)')
    const apply = () => {
      const root = document.documentElement
      root.dataset.theme = theme === 'dark' || (theme === 'auto' && night.matches) ? 'dark' : 'light'
      document
        .querySelector('meta[name="theme-color"]')
        ?.setAttribute('content', getComputedStyle(root).getPropertyValue('--color-paper').trim())
    }
    apply()
    night.addEventListener('change', apply)
    return () => night.removeEventListener('change', apply)
  }, [theme])
  const cycle = () => {
    write('theme', NEXT_THEME[theme])
    setTheme(NEXT_THEME[theme])
  }
  return [theme, cycle] as const
}

function ThemeButton({
  theme,
  onCycle,
  showWord,
  className = '',
}: {
  theme: Theme
  onCycle: () => void
  showWord: boolean
  className?: string
}) {
  const { word, icon: Icon } = THEME_FACE[theme]
  return (
    <button
      onClick={onCycle}
      aria-label={`Theme: ${word}. Switch to ${THEME_FACE[NEXT_THEME[theme]].word}.`}
      title={`Theme: ${word}`}
      className={`press text-ghost hover:text-ink flex items-center gap-1.5 text-xs ${className}`}
    >
      <Icon aria-hidden size={16} strokeWidth={1.75} />
      {showWord && word}
    </button>
  )
}

function Rail({
  collapsed,
  onToggle,
  theme,
  onCycleTheme,
}: {
  collapsed: boolean
  onToggle: () => void
  theme: Theme
  onCycleTheme: () => void
}) {
  const Fold = collapsed ? PanelLeftOpen : PanelLeftClose
  return (
    /* ponytail: width is a cut, not an animation — it would reflow the whole
       page every frame. Worth revisiting in the motion milestone. */
    <aside
      className={`border-rule border-l-cobalt sticky top-0 hidden h-dvh shrink-0 flex-col overflow-y-auto border-r border-l-6 lg:flex ${
        collapsed ? 'w-16' : 'w-52'
      }`}
    >
      <Link
        to="/"
        aria-label="English OS, today"
        className={`font-book text-ink block pt-8 pb-6 text-xl leading-none font-semibold tracking-tight ${
          collapsed ? 'text-center' : 'px-5'
        }`}
      >
        {collapsed ? 'EO' : 'English OS'}
      </Link>

      <nav aria-label="Course" className="flex-1">
        {GROUPS.map((g) => (
          <div key={g.tab} className={g.label ? 'mt-5' : ''}>
            {g.label && !collapsed && (
              <p className="text-ghost mb-1 px-5 text-xs font-semibold tracking-label uppercase">
                {g.label}
              </p>
            )}
            <ul>
              {g.lessons.map((l) => (
                <li key={l.n}>
                  <NavLink
                    to={l.path}
                    end={l.path === '/'}
                    title={collapsed ? l.name : undefined}
                    aria-label={collapsed ? l.name : undefined}
                    className={({ isActive }) =>
                      `press relative flex items-baseline gap-3 py-1.5 text-sm [--press:0.99] ${
                        collapsed ? 'justify-center' : 'px-5'
                      } ${isActive ? 'text-cobalt-deep font-semibold' : 'text-ink-soft hover:text-ink'}`
                    }
                  >
                    {({ isActive }) => (
                      <>
                        {/* The ribbon: the one lesson you have open, marked out of the spine. */}
                        {isActive && (
                          <span aria-hidden className="bg-cobalt absolute top-1/2 left-0 h-0.5 w-3" />
                        )}
                        <span className={`tnum text-xs ${isActive ? '' : 'text-ghost'}`}>{l.n}</span>
                        {!collapsed && l.name}
                      </>
                    )}
                  </NavLink>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </nav>

      <footer
        className={`border-rule mt-6 flex items-center border-t py-4 ${
          collapsed ? 'flex-col gap-3' : 'justify-between px-5'
        }`}
      >
        <ThemeButton theme={theme} onCycle={onCycleTheme} showWord={!collapsed} />
        <button
          onClick={onToggle}
          aria-label={collapsed ? 'Expand the lessons' : 'Collapse the lessons'}
          title={collapsed ? 'Expand' : 'Collapse'}
          className="press text-ghost hover:text-ink"
        >
          <Fold aria-hidden size={16} strokeWidth={1.75} />
        </button>
      </footer>
    </aside>
  )
}

/* The tabs inside a group, on screens with no rail to show them. */
function SectionNav({
  lessons,
  trailing,
}: {
  lessons: Lesson[]
  trailing?: ReactNode
}) {
  return (
    <nav
      aria-label="Section"
      className="border-rule bg-paper sticky top-[env(safe-area-inset-top)] z-20 flex items-stretch gap-6 border-b px-5 lg:hidden"
    >
      {lessons.map((l) => (
        <NavLink
          key={l.path}
          to={l.path}
          className={({ isActive }) =>
            `flex h-11 items-center border-b-2 text-sm ${
              isActive
                ? 'border-cobalt text-cobalt-deep font-semibold'
                : 'text-ink-soft border-transparent'
            }`
          }
        >
          {l.name}
        </NavLink>
      ))}
      {trailing}
    </nav>
  )
}

/* Thumb reach on a phone: five places, each named, never a scrolling list of ten. */
function TabBar({ pathname }: { pathname: string }) {
  return (
    <nav
      aria-label="Course"
      className="border-rule bg-paper fixed inset-x-0 bottom-0 z-30 flex border-t pr-[env(safe-area-inset-right)] pb-[env(safe-area-inset-bottom)] pl-[env(safe-area-inset-left)] lg:hidden"
    >
      {GROUPS.map(({ tab, icon: Icon, lessons }) => {
        const active = lessons.some((l) => isIn(pathname, l.path))
        return (
          <Link
            key={tab}
            to={lessons[0].path}
            aria-current={active ? 'page' : undefined}
            className={`press relative flex h-14 flex-1 flex-col items-center justify-center gap-0.5 text-xs ${
              active ? 'text-cobalt-deep font-semibold' : 'text-ghost'
            }`}
          >
            {active && <span aria-hidden className="bg-cobalt absolute inset-x-5 top-0 h-0.5" />}
            <Icon aria-hidden size={20} strokeWidth={active ? 2 : 1.75} />
            {tab}
          </Link>
        )
      })}
    </nav>
  )
}

export function Shell({ children }: { children: ReactNode }) {
  const { pathname } = useLocation()
  const navType = useNavigationType()
  const [theme, cycleTheme] = useTheme()

  const [railClosed, setRailClosed] = useState(() => read('rail') === 'closed')
  /* A focus page folds the rail whatever the saved choice; opening it there is
     a look around that ends when you leave, not a new preference. */
  const [peekedAt, setPeekedAt] = useState<string | null>(null)
  const peek = peekedAt === pathname
  const focus = isFocus(pathname)
  const collapsed = focus ? !peek : railClosed

  const toggleRail = () => {
    if (focus) return setPeekedAt(peek ? null : pathname)
    write('rail', railClosed ? 'open' : 'closed')
    setRailClosed(!railClosed)
  }

  /* The rail stays in reach now, so you navigate from anywhere on a long page:
     the next one has to start at its top. Back and forward keep the browser's
     own scroll restoration. Focus follows for screen readers, except on load,
     when Tab should still start at the skip link. */
  const main = useRef<HTMLElement>(null)
  const shownPath = useRef(pathname)
  useEffect(() => {
    if (shownPath.current === pathname) return
    shownPath.current = pathname
    if (navType !== 'POP') window.scrollTo(0, 0)
    main.current?.focus({ preventScroll: true })
  }, [pathname, navType])

  const group = GROUPS.find((g) => g.lessons.some((l) => isIn(pathname, l.path)))
  const isRecord = group?.tab === 'More'

  return (
    <div className="flex min-h-dvh pt-[env(safe-area-inset-top)] pr-[env(safe-area-inset-right)] pl-[env(safe-area-inset-left)] lg:p-0">
      <a
        href="#content"
        className="bg-cobalt text-paper sr-only z-40 rounded-sm px-4 py-2 text-sm font-semibold focus:not-sr-only focus:fixed focus:top-3 focus:left-3"
      >
        Skip to the lesson
      </a>
      <h1 className="sr-only">English OS</h1>

      <Rail collapsed={collapsed} onToggle={toggleRail} theme={theme} onCycleTheme={cycleTheme} />

      <main
        id="content"
        ref={main}
        tabIndex={-1}
        className="min-w-0 flex-1 pb-[calc(3.5rem+env(safe-area-inset-bottom))] lg:pb-0"
      >
        {group && group.lessons.length > 1 && !isDeep(pathname) && (
          <SectionNav
            lessons={group.lessons}
            trailing={
              isRecord && (
                <ThemeButton
                  theme={theme}
                  onCycle={cycleTheme}
                  showWord
                  className="ml-auto h-11 pl-3"
                />
              )
            }
          />
        )}
        {children}
      </main>

      <TabBar pathname={pathname} />
    </div>
  )
}
