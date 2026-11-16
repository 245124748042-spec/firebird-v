import { ShieldAlert } from 'lucide-react'
import { useDashboard } from '../hooks/useDashboard'
import { levelFromScore, levelLabel, levelTone, MOVE_WORD, cellName, TEMP_CRIT, TEMP_WARN, SMOKE_CRIT, SMOKE_WARN } from '../lib/format'
import { envOf, roverStatus } from '../lib/simulation'
import Card from './Card'
import EventLog from './EventLog'
import MetricTile from './MetricTile'
import StatusTiles from './StatusTiles'
import Map3D from './Map3D'
import CameraPanel from './CameraPanel'
import { Badge, NoticeBox, SourceBadge } from './Badge'

export default function CommandCenter() {
  const { w, live, backend, allEvents } = useDashboard()
  const st = roverStatus(w), e = envOf(w), lvl = levelFromScore(e.score), t = w.tel
  const real = t.source !== 'SIMULATED'
  const open = allEvents.filter(x => x.severity !== 'Info' && x.status === 'Open').slice(0, 5)
  const battery = real ? backend.status?.battery : w.battery
  const src = t.source === 'LIVE_PI' ? live ? 'LIVE RASPBERRY PI' : 'LAST REAL PI READING' : t.source === 'LIVE_SERIAL' ? live ? 'LIVE SERIAL' : 'LAST REAL SERIAL READING' : 'Simulated'
  return (
    <>
      <NoticeBox kind={real && !live ? 'warn' : 'info'}>{live ? `Temperature, humidity, smoke, distances and risk come from FireBird ${t.source === 'LIVE_PI' ? 'Raspberry Pi Wi-Fi' : 'serial'} telemetry. Battery and flame status are not reported.` : real ? 'Raspberry Pi disconnected. The last real rover and sensor readings are retained.' : 'Rover and sensor values on this page are simulated until FireBird telemetry arrives.'}</NoticeBox>
      <Card title="Rover status" right={<SourceBadge live={live} source={w.tel.source} />}>
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4 lg:grid-cols-6">
          <MetricTile label="Status" value={st} t={st === 'ALERT' ? 'crit' : st === 'AVOIDING OBSTACLE' ? 'warn' : 'info'} />
          <MetricTile label="Grid position" value={cellName(w.rover.r, w.rover.c)} sub="dead-reckoned" />
          <MetricTile label="Goal cell" value={w.goal ? cellName(w.goal.r, w.goal.c) : 'Not selected'} />
          <MetricTile label="Battery" value={battery == null ? 'Not reported' : `${battery.toFixed(0)}%`} sub={real ? 'Not reported by FireBird' : 'Simulated'} />
          <MetricTile label="Movement" value={MOVE_WORD[t.movement]} />
          <MetricTile label="Obstacle" value={t.obstacleDetected ? 'DETECTED' : 'CLEAR'} t={t.obstacleDetected ? 'warn' : 'ok'} />
          <MetricTile label="Person count" value={w.personCount} sub={w.personLive ? 'Laptop camera' : src} />
          <MetricTile label="Temperature" value={`${e.temp.toFixed(1)} Â°C`} sub={src} t={e.temp >= TEMP_CRIT ? 'crit' : e.temp >= TEMP_WARN ? 'warn' : 'gray'} />
          <MetricTile label="Humidity" value={`${e.hum.toFixed(1)} %`} sub={src} />
          <MetricTile label="Smoke level" value={e.smoke} sub={`${src} (raw)`} t={e.smoke >= SMOKE_CRIT ? 'crit' : e.smoke >= SMOKE_WARN ? 'warn' : 'gray'} />
          <MetricTile label="Maximum temperature" value={`${w.maxTemp.toFixed(1)} Â°C`} sub="since mode start" />
          <MetricTile label="Fire-risk level" value={levelLabel[lvl]} t={levelTone(lvl)} sub={`score ${e.score}/100`} />
        </div>
      </Card>
      <StatusTiles />
      <div className="grid items-stretch gap-4 xl:grid-cols-2">
        <Map3D mode="live" />
        <Map3D mode="route" />
      </div>
      <CameraPanel />
      <div className="space-y-4">
        <Card title="Recent alerts" icon={<ShieldAlert size={16} className="text-ember" />}>
          {open.length === 0 ? <p className="text-sm text-slate-600">No open warnings.</p> :
            <ul className="space-y-2 text-sm">{open.map(x => <li key={x.id}><Badge kind={x.severity === 'Critical' ? 'crit' : 'warn'}>{x.severity}</Badge> {x.event}</li>)}</ul>}
        </Card>
        <EventLog />
      </div>
    </>
  )
}

