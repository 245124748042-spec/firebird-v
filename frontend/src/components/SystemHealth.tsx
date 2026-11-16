import { useDashboard } from '../hooks/useDashboard'
import { fmtTime } from '../lib/format'
import Card from './Card'
import { NoticeBox } from './Badge'

type Lvl = 'ok' | 'warn' | 'bad'
const dot: Record<Lvl, string> = { ok: 'bg-ok', warn: 'bg-ember', bad: 'bg-alarm' }

export default function SystemHealth() {
  const { w, backend: b, live } = useDashboard()
  const st = b.status, s = st?.serial, p = b.person, pi = st?.raspberryPi
  const usingPi = !!pi?.enabled
  const realTelemetry = w.tel.source !== 'SIMULATED'
  const hl = (h?: string): Lvl => (h === 'ok' ? 'ok' : h === 'error' ? 'bad' : 'warn')
  const rows: [string, string, Lvl][] = [
    ['Dashboard', 'Running', 'ok'],
    ['Backend service', b.online ? 'Online' : 'Offline', b.online ? 'ok' : 'bad'],
    [usingPi ? 'Raspberry Pi Wi-Fi' : 'Serial connection', usingPi ? (pi?.connected ? 'Connected, receiving telemetry' : 'Not connected') : !s ? 'Unknown (backend offline)' : s.connected ? (live ? 'Connected, receiving telemetry' : 'Open, no telemetry yet') : 'Not connected', live ? 'ok' : s?.connected || pi?.connected ? 'warn' : 'bad'],
    ['Serial port', usingPi ? 'Raspberry Pi bridge' : s?.port ?? '-', usingPi ? 'ok' : s?.port ? 'ok' : 'warn'],
    ['Baud rate', usingPi ? '9600 (Pi to FireBird)' : s?.baudRate ? String(s.baudRate) : '-', 'ok'],
    ['FireBird controller', st ? st.controller : 'Unknown', st?.controller === 'online' ? 'ok' : 'warn'],
    ['YOLO model', usingPi && p?.modelLoaded == null ? 'Pi status unavailable' : p ? (p.modelLoaded ? 'Loaded' : 'Not loaded') : st?.model ? (st.model.loaded ? 'Loaded' : 'Not loaded') : 'Unknown', (p?.modelLoaded ?? st?.model.loaded) ? 'ok' : 'warn'],
    ['Model path', p?.modelPath ?? st?.model.path ?? '-', 'ok'],
    ['Camera', usingPi ? 'Status unavailable on Pi (preview not streamed)' : p ? (p.cameraActive ? 'Active' : 'Stopped') : 'Unknown', !usingPi && p?.cameraActive ? 'ok' : 'warn'],
    ['Camera FPS', p?.cameraActive ? p.fps.toFixed(1) : '-', 'ok'],
    ['Inference latency', p?.cameraActive ? `${p.latencyMs.toFixed(0)} ms` : '-', 'ok'],
    ['RAIR planner', st ? (st.planner === 'ready' ? 'Backend planner ready' : 'Backend planner unavailable, local simulation planner in use') : 'Local simulation planner in use', st?.planner === 'ready' ? 'ok' : 'warn'],
    ['Last telemetry', b.telemetryAt ? fmtTime(b.telemetryAt) : 'Never', b.telemetryAt ? 'ok' : 'warn'],
    ['Encoder odometry', !live ? 'Waiting for live telemetry' : b.map?.odometryAvailable ? 'Active; distance depends on measured calibration' : b.map?.odometryStatus === 'calibration_missing' ? 'Calibration required: wheel diameter, track, pulses/rev and map cell size' : b.map?.odometryStatus === 'encoder_data_unavailable' ? 'Encoder counts unavailable' : 'Waiting for encoder movement', b.map?.odometryAvailable ? 'ok' : 'warn'],
    ['Battery', realTelemetry ? 'Not reported' : live ? (st?.battery == null ? 'Not reported' : `${st.battery.toFixed(0)}%`) : `${w.battery.toFixed(0)}% (simulated)`, 'warn'],
    ['DHT22 sensor', st ? st.sensors.dht22 : 'Unknown', hl(st?.sensors.dht22)],
    ['Smoke sensor', st ? st.sensors.smoke : 'Unknown', hl(st?.sensors.smoke)]
  ]
  return (
    <>
      <NoticeBox kind="info">Values not reported by FireBird remain unavailable or are estimated by the dashboard.</NoticeBox>
      <Card title="Diagnostic checklist">
        <ul className="divide-y divide-line">{rows.map(([k, v, l]) => (
          <li key={k} className="flex items-center justify-between gap-3 py-2 text-sm">
            <span className="flex items-center gap-2"><span className={`h-2.5 w-2.5 rounded-full ${dot[l]}`} aria-hidden />{k}<span className="sr-only">{l === 'ok' ? 'OK' : l === 'warn' ? 'warning' : 'error'}</span></span>
            <span className="break-all text-right font-mono text-xs text-slate-700">{v}</span></li>))}</ul>
      </Card>
    </>
  )
}
