import { Flame, Pause, Play, Plug, PlugZap, RotateCcw } from 'lucide-react'
import { useDashboard } from '../hooks/useDashboard'
import Button from './Button'
import { ModeBadge, NoticeBox } from './Badge'

export const PAGES: [string, string][] = [['command', 'Command Center'], ['map', 'Map and Route'], ['person', 'Person Detection'], ['environment', 'Environment and Fire'], ['telemetry', 'Telemetry and Alerts'], ['health', 'System Health']]

export default function Header({ page, setPage }: { page: string; setPage: (p: string) => void }) {
  const { w, backend: b, live, act, reset, speed, setSpeed, connectRobot, disconnectRobot, connectingRobot } = useDashboard()
  const s = b.status?.serial
  const piMode = !!b.status?.raspberryPi?.enabled
  return (
    <>
      <header className="sticky top-0 z-20 border-b border-line bg-panel">
        <div className="mx-auto flex max-w-[1500px] flex-wrap items-center justify-between gap-3 px-4 py-2.5">
          <button onClick={() => setPage('home')} className="flex items-center gap-2 text-left" aria-label="Back to home">
            <Flame className="text-ember" size={22} /><span><span className="block font-semibold leading-tight text-slate-900">FireBird</span><span className="block text-[11px] text-slate-600">Hazard detection and risk mapping</span></span>
          </button>
          <div className="flex flex-wrap items-center gap-2">
            <ModeBadge />
            {!b.checked ? <span className="rounded-md border border-line bg-base px-2 py-1.5 text-xs text-slate-600">Checking backend...</span>
              : <span className={`rounded-md border px-2 py-1.5 font-mono text-xs ${b.online ? 'border-ok/50 bg-ok/10 text-ok' : 'border-line bg-base text-slate-700'}`}>{b.online ? `Backend online | ${live && b.telemetry?.source === 'LIVE_PI' ? 'Raspberry Pi connected' : piMode ? 'Raspberry Pi disconnected' : `COM: ${s?.connected ? `${s.port} @ ${s.baudRate}` : 'not connected'}`}` : 'Backend service offline'}</span>}
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Button onClick={() => act(x => (x.running = !x.running))} disabled={live} title={live ? 'Simulation is stopped in live mode' : ''}>{w.running ? <Pause size={14} /> : <Play size={14} />}{w.running ? 'Pause' : 'Start'} sim</Button>
            <Button onClick={reset}><RotateCcw size={14} />Reset</Button>
            <select aria-label="Simulation speed" value={speed} onChange={e => setSpeed(+e.target.value)} className="rounded-md border border-line bg-base px-2 py-1.5 text-sm">
              {[0.5, 1, 2].map(n => <option key={n} value={n}>{n}x</option>)}</select>
            <Button onClick={connectRobot} disabled={!b.online || live || connectingRobot || piMode}><PlugZap size={14} />{connectingRobot ? 'Connecting...' : piMode ? live ? 'Raspberry Pi Connected' : 'Pi Disconnected' : live ? 'Robot Connected' : 'Connect Robot'}</Button>
            <Button onClick={disconnectRobot} disabled={!b.online || !s?.connected}><Plug size={14} />Disconnect</Button>
          </div>
        </div>
        <nav className="mx-auto flex max-w-[1500px] gap-1 overflow-x-auto px-4" aria-label="Pages">
          {PAGES.map(([id, label]) => (
            <button key={id} onClick={() => setPage(id)} aria-current={page === id}
              className={`whitespace-nowrap border-b-2 px-3 py-2 text-sm ${page === id ? 'border-ember font-semibold text-slate-900' : 'border-transparent text-slate-600 hover:text-slate-900'}`}>{label}</button>
          ))}
        </nav>
      </header>
      {b.checked && !b.online && <div className="mx-auto mt-3 max-w-[1500px] px-4"><div role="alert"><NoticeBox kind="warn">Backend service offline. Staying in SIMULATION MODE. Start it with <code className="font-mono">python main.py</code> to use serial, camera and the backend planner.</NoticeBox></div></div>}
      {b.online && piMode && !live && <div className="mx-auto mt-3 max-w-[1500px] px-4"><NoticeBox kind="warn">Raspberry Pi disconnected. SIMULATION MODE is active. The laptop serial port is disabled in Raspberry Pi mode.</NoticeBox></div>}
      {b.online && !piMode && !live && s && !s.connected && <div className="mx-auto mt-3 max-w-[1500px] px-4"><NoticeBox kind="warn">{connectingRobot ? `Connecting to ${s.port ?? 'COM3'} and waiting for verified $FB telemetry...` : `Disconnected. SIMULATION MODE is active.${s.error ? ` ${s.error}` : ' Press Connect Robot to retry.'}`}</NoticeBox></div>}
      {b.online && !live && s?.connected && <div className="mx-auto mt-3 max-w-[1500px] px-4"><NoticeBox kind="info">Serial port {s.port} is open but valid FireBird telemetry is not arriving. Staying in SIMULATION MODE. Check the firmware baud rate and `$FB` CSV format, then press Connect Robot to retry.</NoticeBox></div>}
    </>
  )
}
