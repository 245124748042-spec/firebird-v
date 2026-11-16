import { Pause, Play, Route as RouteIcon, Send, Square, OctagonAlert } from 'lucide-react'
import { useDashboard } from '../hooks/useDashboard'
import Button from './Button'
import Card from './Card'
import MetricTile from './MetricTile'
import { Badge } from './Badge'

export default function RoutePlanner() {
  const { w, act, live, backend, calculate, sendRoute, planning, startNavigation, pauseNavigation, resumeNavigation, stopNavigation, emergencyStop, resetEmergencyStop } = useDashboard()
  const r = w.route, extra = r.found ? r.path.length - 1 - r.shortestLength : 0
  const destinationAvailable = live ? !!(w.goal || backend.map?.goal || backend.status?.goal) : !!w.goal
  const piMode = !!backend.status?.raspberryPi?.enabled
  const executor = backend.status?.route as { state?: string; index?: number; total?: number; nextCommand?: string; emergencyStopLatched?: boolean } | undefined
  const executorState = executor?.state ?? 'IDLE'
  const emergencyStopLatched = !!executor?.emergencyStopLatched
  const telemetryFresh = backend.telemetryAt !== null && Date.now() - backend.telemetryAt < 1500
  const calibrated = backend.map?.odometryStatus === 'available'
  const robotStopped = backend.telemetry?.movement === 'S'
  const hazardStop = !!backend.telemetry?.obstacleDetected || (backend.telemetry?.riskScore ?? 0) >= 75
    || backend.status?.fireRiskLevel === 'CRITICAL' || !!((backend.telemetry?.flags ?? 0) & 0x07)
  const communicationReady = piMode ? !!backend.status?.raspberryPi?.connected : !!backend.status?.serial.connected
  const sensorsReady = backend.status?.sensors.dht22 === 'ok' && backend.status?.sensors.smoke === 'ok'
  const navigationReady = live && communicationReady && telemetryFresh && calibrated && sensorsReady && robotStopped && !hazardStop && !emergencyStopLatched
    && !['FAILED', 'BLOCKED', 'STOPPING'].includes(executorState)
    && r.found && r.planner === 'backend'
  const navigationBlock = !live ? 'Waiting for fresh FireBird telemetry.'
    : !communicationReady ? (piMode ? 'Raspberry Pi bridge is unavailable.' : 'FireBird serial communication is unavailable.')
    : !telemetryFresh ? 'Telemetry is stale.'
    : !calibrated ? 'Encoder odometry is not calibrated or has not produced a position yet.'
    : !sensorsReady ? 'Required environmental sensor health is unavailable.'
    : emergencyStopLatched ? 'Emergency stop is latched; reset it after confirming the rover is stopped and safe.'
    : !robotStopped ? 'FireBird reports movement in progress.'
    : hazardStop ? 'Obstacle or critical hazard stop is active.'
    : ['FAILED', 'BLOCKED'].includes(executorState) ? 'Navigation is locked after a failure; use Emergency Stop and verify the rover.'
    : executorState === 'STOPPING' ? 'Waiting for the stop command acknowledgement.'
    : !r.found || r.planner !== 'backend' ? 'Calculate a backend route first.' : ''
  const navigating = executorState === 'FOLLOWING' || executorState === 'STOPPING'
  const navStatus = planning ? 'Planning route'
    : executorState === 'COMPLETE' ? 'ARRIVED · Destination reached'
    : executorState === 'FAILED' || executorState === 'BLOCKED' ? 'Navigation failed'
    : executorState === 'PAUSED' ? 'PAUSED · Navigation paused'
    : executorState === 'STOPPING' ? 'STOPPING · waiting for Pi bridge acknowledgement'
    : executorState === 'IDLE' && (executor?.total ?? 0) > 0 ? 'Navigation stopped'
    : navigating && backend.telemetry?.obstacleDetected ? 'Obstacle detected'
    : navigating && backend.telemetry?.movement === 'F' ? 'Moving forward'
    : navigating && backend.telemetry?.movement === 'B' ? 'Moving backward'
    : navigating && backend.telemetry?.movement === 'L' ? 'Turning left'
    : navigating && backend.telemetry?.movement === 'R' ? 'Turning right'
    : navigating ? `EXECUTING · awaiting encoder confirmation${executor?.index != null && executor.total ? ` (${executor.index}/${executor.total})` : ''}`
    : r.found && r.status.startsWith('Route ready; automatic navigation not started:') ? r.status
    : r.found ? 'READY · Route ready' : destinationAvailable ? 'DESTINATION_SELECTED' : 'IDLE'
  const confirmStart = () => {
    if (window.confirm('Start navigation on the FireBird rover using this route? The rover will move only after backend safety checks pass.')) void startNavigation()
  }
  return (
    <Card title="RAIR-inspired route planner" right={r.planner === 'backend' ? <Badge kind="info">BACKEND PLANNER</Badge> : r.planner === 'local' ? <Badge kind="sim">LOCAL SIMULATION PLANNER</Badge> : undefined}>
      <label className="block text-sm text-slate-800">Risk attitude (alpha): <span className="font-mono font-semibold">{w.alpha.toFixed(1)}</span>
        <input type="range" min={0.5} max={5} step={0.1} value={w.alpha} onChange={e => act(x => (x.alpha = +e.target.value))} className="mt-1 w-full" aria-label="Risk attitude alpha" />
        <span className="flex justify-between text-xs text-slate-600"><span>Risk-seeking ←</span><span>→ Risk-averse</span></span>
      </label>
      <div className="my-3 flex flex-wrap gap-2">
        <Button kind="primary" disabled={planning || !destinationAvailable} onClick={calculate}><RouteIcon size={14} />{planning ? 'Calculating...' : 'Calculate RAIR Route'}</Button>
        {live ? <>
          <Button kind="primary" disabled={!navigationReady || navigating || executorState === 'PAUSED'} title={navigationReady ? 'Explicitly start the planned route' : navigationBlock} onClick={confirmStart}><Play size={14} />Start Navigation</Button>
          <Button disabled={!navigating || executorState === 'STOPPING'} onClick={() => void pauseNavigation()}><Pause size={14} />Pause Navigation</Button>
          <Button disabled={executorState !== 'PAUSED'} onClick={() => void resumeNavigation()}><Play size={14} />Resume Navigation</Button>
          <Button disabled={!navigating && executorState !== 'PAUSED'} onClick={() => void stopNavigation()}><Square size={14} />Cancel Mission</Button>
          <Button kind="danger" disabled={!backend.online} onClick={() => void emergencyStop()} title="Sends the existing MOVE:STOP command; not a separate hardware E-stop"><OctagonAlert size={14} />Emergency Stop</Button>
          {emergencyStopLatched && <Button disabled={!communicationReady || !telemetryFresh || !robotStopped || hazardStop || !sensorsReady} onClick={() => { if (window.confirm('Reset the software emergency stop latch? Confirm the rover is physically stopped and the area is safe.')) void resetEmergencyStop() }}>Reset Emergency Stop</Button>}
        </> : <>
          <Button onClick={sendRoute} disabled={planning || !destinationAvailable}><Send size={14} />Follow Simulated Route</Button>
          <Button disabled={!w.following || w.paused} onClick={() => act(x => { x.paused = true; x.outbox.push('MOVE:STOP') })}><Pause size={14} />Pause Simulation</Button>
          <Button disabled={!w.following || !w.paused} onClick={() => act(x => (x.paused = false))}><Play size={14} />Resume Simulation</Button>
        </>}
      </div>
      <div className="mb-3 flex flex-wrap items-center gap-2 text-sm">
        {!destinationAvailable ? <Badge>AWAITING DESTINATION</Badge> : r.planner === 'none' ? <Badge>NO ROUTE CALCULATED</Badge> : r.found ? <Badge kind="ok">ROUTE FOUND</Badge> : <Badge kind="crit">NO ROUTE FOUND</Badge>}
        <span className="text-slate-600">{live ? navStatus : w.following ? (w.paused ? 'Simulation route paused' : 'Following route (simulated rover).') : !destinationAvailable ? 'Select a destination to calculate a route.' : r.status}</span>
      </div>
      {live && !navigationReady && !navigating && <p className="mb-3 rounded-md border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900">Navigation unavailable: {navigationBlock}</p>}
      {live && <p className="mb-3 text-xs text-slate-500">Emergency Stop sends the existing C:S stop command through the active serial owner. The telemetry protocol has no separate emergency-stop status or hardware E-stop acknowledgement.</p>}
      {!destinationAvailable && <p className="mb-3 rounded-md border border-line bg-base/60 p-3 text-sm text-slate-700">{live ? 'Click a cell on the live route map to set the destination.' : 'Select the Goal tool and choose a map cell to set the destination.'}</p>}
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        <MetricTile label="Route length" value={r.found ? r.path.length - 1 : '-'} sub="moves" />
        <MetricTile label="Route risk" value={r.found ? r.risk : '-'} sub="sum of cell risk" />
        <MetricTile label="Shortest-route risk" value={r.found ? r.shortestRisk : '-'} />
        <MetricTile label="Extra moves" value={r.found ? (extra > 0 ? `+${extra}` : extra) : '-'} t={extra > 0 ? 'warn' : 'gray'} sub="vs shortest" />
      </div>
      {r.explanation && <p className="mt-3 rounded-md border border-line bg-base/60 p-3 text-sm text-slate-700"><span className="font-semibold">Planner explanation: </span>{r.explanation}</p>}
      <h3 className="mb-1 mt-3 text-sm font-semibold text-slate-900">Command queue</h3>
      {r.cmds.length === 0 ? <p className="text-sm text-slate-600">Calculate a route to see commands.</p> : (
        <ol className="flex max-h-36 flex-wrap gap-1 overflow-y-auto font-mono text-xs">
          {r.cmds.map((c, i) => <li key={i} className={`rounded border px-1.5 py-0.5 ${i < w.qi ? 'border-line bg-base text-slate-400' : i === w.qi && w.following ? 'border-scan bg-scan/10 text-scan' : 'border-line text-slate-700'}`}>{c}</li>)}
        </ol>)}
      <p className="mt-2 text-xs text-slate-500">RAIR-inspired heuristic: A* with a risk penalty scaled by alpha. Critical cells are never entered. Not the published RAIR algorithm.</p>
    </Card>
  )
}
