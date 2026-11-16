import type { Cell } from '../types'
import { cellName, levelFromScore, parseCell } from '../lib/format'
import { hotList, riskOf } from '../lib/simulation'
import { useDashboard } from '../hooks/useDashboard'
import Card from './Card'
import { Badge } from './Badge'

const FILL = { SAFE: '#bbf7d0', CAUTION: '#fde047', WARNING: '#fdba74', CRITICAL: '#f87171' }

export function MapLegend() {
  const item = (c: string, t: string, round = false) => <li key={t} className="flex items-center gap-1.5"><span className={`h-3 w-3 border border-line ${round ? 'rounded-full' : 'rounded-sm'}`} style={{ background: c }} />{t}</li>
  return (
    <ul className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-600">
      {item('#bbf7d0', 'Safe')}{item('#fde047', 'Caution')}{item('#fdba74', 'Suspected hazard')}{item('#f87171', 'Critical / fire-risk')}{item('#94a3b8', 'Obstacle / blocked')}
      {item('#0284c7', 'Rover', true)}{item('#fff', 'Goal', true)}{item('#0f172a', 'Person', true)}{item('#b45309', 'Hazard / hotspot', true)}
      <li className="flex items-center gap-1.5"><span className="h-0.5 w-5 bg-scan" />Planned route</li>
      <li className="flex items-center gap-1.5"><span className="w-5 border-t-2 border-dashed border-slate-500" />Previous route</li>
      <li className="flex items-center gap-1.5"><span className="w-5 border-t-2 border-violet-600" />Encoder travelled path</li>
    </ul>
  )
}

export default function ArenaMap({ interactive = true, title = 'Risk map' }: { interactive?: boolean; title?: string }) {
  const { w, click, live, backend } = useDashboard()
  const n = live && backend.map ? backend.map.rows : w.size
  const backendCells = live && backend.map ? backend.map.cells : null
  const risk = backendCells
    ? Array.from({ length: n }, (_, r) => Array.from({ length: n }, (_, c) => backendCells[r * n + c]?.riskScore ?? 0))
    : riskOf(w)
  const isObstacle = (r: number, c: number) => backendCells ? !!backendCells[r * n + c]?.isObstacle : w.obs[r][c]
  const ctr = (c: Cell) => `${c.c + 0.5},${c.r + 0.5}`
  const pts = (p: Cell[]) => p.map(ctr).join(' ')
  const rover = live && backend.map ? { r: backend.map.rover.row, c: backend.map.rover.column, h: ['N', 'E', 'S', 'W'].indexOf(backend.map.rover.heading) } : w.rover
  const actualTrail = live && backend.map?.odometryAvailable ? backend.map.odometryPath : []
  const roverPoint = actualTrail.length ? actualTrail[actualTrail.length - 1] : { x: rover.c + 0.5, y: rover.r + 0.5 }
  // Encoder odometry reports the rover's true orientation, including rotations
  // in place. Fall back to the map's cardinal heading before a pose is available.
  const headingDegrees = live && backend.map?.odometryHeadingRad != null
    ? 90 - backend.map.odometryHeadingRad * 180 / Math.PI
    : rover.h * 90
  const viewRadius = 1.75
  const viewBox = `${roverPoint.x - viewRadius} ${roverPoint.y - viewRadius} ${viewRadius * 2} ${viewRadius * 2}`
  const goal = live ? (backend.map?.goal ? parseCell(backend.map.goal) : null) : w.goal
  return (
    <Card title={`${title} · local view`} right={backend.map?.odometryAvailable ? <Badge kind="live">WHEEL ODOMETRY</Badge> : live ? <Badge kind="live">LIVE RISK · {backend.map?.odometryStatus === 'calibration_missing' ? 'CALIBRATION MISSING' : backend.map?.odometryStatus === 'encoder_data_unavailable' ? 'ENCODER DATA UNAVAILABLE' : 'ODOMETRY UNAVAILABLE'}</Badge> : <Badge kind="sim">SIMULATED MAP</Badge>}>
      <svg viewBox={viewBox} className="mx-auto aspect-square w-full max-w-[480px] rounded border border-line bg-white" role="img" aria-label="Rover centered on a compact local map showing hazards, actual travelled trail and planned route">
        <rect x={roverPoint.x - viewRadius} y={roverPoint.y - viewRadius} width={viewRadius * 2} height={viewRadius * 2} fill="#fff" />
        {risk.map((row, r) => row.map((v, c) => (
          <rect key={`${r}-${c}`} x={c} y={r} width={1} height={1} stroke="#fff" strokeWidth={0.018} fill={isObstacle(r, c) ? '#94a3b8' : FILL[levelFromScore(v)]}
            onClick={interactive ? () => click({ r, c }) : undefined} style={{ cursor: interactive ? 'pointer' : 'default' }}><title>{cellName(r, c)}</title></rect>
        )))}
        {!live && w.prev && w.prev.length > 1 && <polyline points={pts(w.prev)} fill="none" stroke="#64748b" strokeWidth={0.025} strokeDasharray="0.12 0.1" />}
        {w.route.found && (!live || w.route.planner === 'backend') && <polyline points={pts(w.route.path)} fill="none" stroke="#0284c7" strokeWidth={0.045} strokeLinejoin="round" strokeLinecap="round" />}
        {actualTrail.length > 1 && <polyline points={actualTrail.map(p => `${p.x},${p.y}`).join(' ')} fill="none" stroke="#7c3aed" strokeWidth={0.03} strokeLinejoin="round" strokeLinecap="round" />}
        {backendCells ? backendCells.filter(c => c.isFire).map(c => <circle key={`fire-${c.row}-${c.column}`} cx={c.column + 0.5} cy={c.row + 0.5} r={0.3} fill="none" stroke="#b45309" strokeWidth={0.04} />) : hotList(w).map((h, i) => <circle key={i} cx={h.c + 0.5} cy={h.r + 0.5} r={0.3} fill="none" stroke="#b45309" strokeWidth={0.04} />)}
        {(backendCells ? backendCells.filter(c => c.isPerson).map(c => ({ r: c.row, c: c.column })) : w.persons).map((p, i) => <circle key={i} cx={p.c + 0.5} cy={p.r + 0.5} r={0.16} fill="#0f172a" />)}
        {goal && <><circle cx={goal.c + 0.5} cy={goal.r + 0.5} r={0.25} fill="#fff" stroke="#0284c7" strokeWidth={0.04} /><text x={goal.c + 0.5} y={goal.r + 0.58} fontSize={0.2} textAnchor="middle" fill="#0c4a6e" fontWeight={700}>G</text></>}
        {w.sel && <rect x={w.sel.c} y={w.sel.r} width={1} height={1} fill="none" stroke="#0f172a" strokeWidth={0.04} />}
        <g transform={`translate(${roverPoint.x} ${roverPoint.y}) rotate(${headingDegrees})`}><circle r={0.22} fill="#e0f2fe" stroke="#0c4a6e" strokeWidth={0.035} /><polygon points="0,-0.2 0.14,0.12 -0.14,0.12" fill="#0284c7" stroke="#0c4a6e" strokeWidth={0.025} /></g>
      </svg>
      <MapLegend />
    </Card>
  )
}
