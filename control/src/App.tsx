import { useEffect, useState } from 'react'

import { getHealth } from './api/health'

type ApiStatus = 'checking' | 'online' | 'offline'

export function App() {
  const [apiStatus, setApiStatus] = useState<ApiStatus>('checking')

  useEffect(() => {
    let active = true
    getHealth()
      .then(() => active && setApiStatus('online'))
      .catch(() => active && setApiStatus('offline'))
    return () => {
      active = false
    }
  }, [])

  return (
    <main className="shell">
      <header className="topbar">
        <a className="brand" href="/" aria-label="RaceCore Control home">
          <span className="brand-mark">RC</span>
          <span>RACECORE <small>CONTROL</small></span>
        </a>
        <span className={`api-status api-status--${apiStatus}`}>
          <i aria-hidden="true" />
          API {apiStatus}
        </span>
      </header>

      <section className="welcome">
        <p className="eyebrow">RACE OPERATIONS</p>
        <h1>Race control</h1>
        <p className="intro">Your live sessions and race direction tools will appear here.</p>
      </section>

      <section className="empty-card" aria-live="polite">
        <div className="track-glyph" aria-hidden="true">◎</div>
        <h2>No active session</h2>
        <p>Create a session through the RaceCore API to begin. Session controls will be added here.</p>
        <code>POST /api/v1/sessions</code>
      </section>
      <footer>LOCAL RACE CONTROL <span>·</span> ASSETTO CORSA</footer>
    </main>
  )
}
