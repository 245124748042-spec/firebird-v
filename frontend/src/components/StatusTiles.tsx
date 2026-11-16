import { Activity, Route, Thermometer, Users } from 'lucide-react'
import { useDashboard } from '../hooks/useDashboard'
import { levelFromScore, levelLabel, levelTone, MOVE_WORD } from '../lib/format'
import { envOf } from '../lib/simulation'
import StatusTile from './StatusTile'
import { Badge, SourceBadge } from './Badge'

export default function StatusTiles() {
  const { w, live, backend } = useDashboard()
  const t = w.tel, e = envOf(w), lvl = levelFromScore(e.score), r = w.route
  const pi = backend.status?.raspberryPi
  const piCountRecent = !!pi?.lastPersonCountAt && Date.now() - Date.parse(pi.lastPersonCountAt) < 5000
  const personCount = pi?.enabled ? backend.person?.count ?? pi.personCount ?? null : w.personCount
  const hasGoal = live ? !!(backend.map?.goal || backend.status?.goal) : !!w.goal
  return (
    <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-4">
      <StatusTile icon={<Activity size={16} />} title="Obstacle Avoidance" badge={<SourceBadge live={live} source={t.source} />} value={t.obstacleDetected ? 'OBSTACLE' : 'CLEAR'} t={t.obstacleDetected ? 'warn' : 'ok'}
        sub={`L ${t.leftIr}  C ${t.centerIr}  R ${t.rightIr}  S ${t.sideIr}${t.ir5 == null ? '' : `  IR5 ${t.ir5}`}  ${MOVE_WORD[t.movement]}`} />
      <StatusTile icon={<Route size={16} />} title="RAIR/A* Path Planning" badge={r.planner === 'backend' ? <Badge kind="info">BACKEND</Badge> : hasGoal ? <Badge kind="sim">SIMULATION</Badge> : <Badge kind="gray">AWAITING DESTINATION</Badge>}
        value={r.found ? `${r.path.length - 1} moves` : hasGoal ? 'No safe route' : 'Select a destination'} t={r.found ? 'info' : hasGoal ? 'warn' : 'gray'} sub={r.found ? `alpha ${w.alpha.toFixed(1)} | ${r.status}` : hasGoal ? `alpha ${w.alpha.toFixed(1)} | ${r.status}` : 'Select a destination to calculate a route'} />
      <StatusTile icon={<Users size={16} />} title="Person Detection" badge={w.personLive ? <Badge kind="live">LIVE CAMERA</Badge> : pi?.enabled ? personCount == null ? <Badge kind="warn">YOLO COUNT WAITING</Badge> : <Badge kind={piCountRecent ? 'live' : 'warn'}>{piCountRecent ? 'LIVE PI YOLO' : 'LAST PI COUNT'}</Badge> : live && w.tel.source === 'LIVE_PI' ? <Badge kind="live">LIVE PI FRAME</Badge> : live ? <Badge kind="live">LIVE SERIAL</Badge> : <Badge kind="sim">SIMULATED</Badge>}
        value={personCount == null ? 'Waiting for YOLO' : `${personCount} visible`} t={personCount == null ? 'gray' : personCount ? 'warn' : 'ok'} sub={w.personLive ? 'YOLO on laptop camera' : pi?.enabled ? 'Count from Raspberry Pi YOLO' : live ? 'Count reported by FireBird' : 'Simulated people on map'} />
      <StatusTile icon={<Thermometer size={16} />} title="Thermal & Fire Monitoring" badge={<SourceBadge live={live} source={t.source} />} value={levelLabel[lvl]} t={levelTone(lvl)}
        sub={`${e.temp.toFixed(1)} Â°C  ${e.hum.toFixed(1)} %  smoke ${e.smoke}`} />
    </div>
  )
}

