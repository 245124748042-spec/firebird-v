import { useDashboard } from '../hooks/useDashboard'
import { getCell } from '../lib/simulation'
import { fmtTime, levelLabel } from '../lib/format'
import Card from './Card'
import { Badge } from './Badge'

export default function CellDetails() {
  const { w, live } = useDashboard()
  const c = w.sel ? getCell(w, w.sel.r, w.sel.c) : null
  const status = !c ? '' : c.isObstacle ? 'Obstacle (blocked)' : c.isFire ? 'Hazard / fire-risk' : c.isPerson ? 'Person present' : w.rover.r === c.row && w.rover.c === c.column ? 'Rover here' : 'Free'
  return (
    <Card title="Cell details" right={c && <Badge kind={live ? 'live' : 'sim'}>{live ? 'LIVE WHERE MEASURED' : 'SIMULATED'}</Badge>}>
      {!c ? <p className="text-sm text-slate-600">Click a cell on the map.</p> : (
        <dl className="grid grid-cols-2 gap-x-3 gap-y-1 text-sm">
          <dt className="text-slate-600">Coordinate</dt><dd className="font-mono">{c.coordinate} (row {c.row + 1}, col {c.column + 1})</dd>
          <dt className="text-slate-600">Cell status</dt><dd>{status}</dd>
          <dt className="text-slate-600">Obstacle</dt><dd>{c.isObstacle ? 'Yes' : 'No'}</dd>
          <dt className="text-slate-600">Person</dt><dd>{c.isPerson ? 'Yes' : 'No'}</dd>
          <dt className="text-slate-600">Temperature</dt><dd className="font-mono">{c.temperature == null ? 'Not measured' : `${c.temperature.toFixed(1)} °C`}</dd>
          <dt className="text-slate-600">Smoke level</dt><dd className="font-mono">{c.smoke == null ? 'Not measured' : c.smoke}</dd>
          <dt className="text-slate-600">Fire-risk level</dt><dd>{levelLabel[c.riskLevel]}</dd>
          <dt className="text-slate-600">Risk score</dt><dd className="font-mono">{c.riskScore}/100</dd>
          <dt className="text-slate-600">Last updated</dt><dd className="font-mono">{fmtTime(c.lastUpdated)}</dd>
        </dl>)}
    </Card>
  )
}
