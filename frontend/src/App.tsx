import { useState } from 'react'
import { DashboardProvider } from './hooks/useDashboard'
import Header from './components/Header'
import Home from './components/Home'
import CommandCenter from './components/CommandCenter'
import MapPage from './components/MapPage'
import PersonDetection from './components/PersonDetection'
import EnvironmentMonitoring from './components/EnvironmentMonitoring'
import TelemetryConsole from './components/TelemetryConsole'
import SystemHealth from './components/SystemHealth'

const PAGES: Record<string, () => JSX.Element> = { command: CommandCenter, map: MapPage, person: PersonDetection, environment: EnvironmentMonitoring, telemetry: TelemetryConsole, health: SystemHealth }

export default function App() {
  const [page, setPage] = useState('home')
  const Page = PAGES[page] ?? CommandCenter
  return (
    <DashboardProvider active={page !== 'home'}>
      {page === 'home' ? <Home onOpen={() => setPage('command')} /> : (
        <div className="min-h-screen"><Header page={page} setPage={setPage} /><main className="mx-auto max-w-[1500px] space-y-4 p-4"><Page /></main></div>
      )}
    </DashboardProvider>
  )
}
