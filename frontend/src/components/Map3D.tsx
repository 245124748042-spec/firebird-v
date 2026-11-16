import { useCallback, useEffect, useRef, useState } from 'react'
import { Minus, Plus, RotateCcw } from 'lucide-react'
import { useDashboard } from '../hooks/useDashboard'
import { cellName, levelFromScore, parseCell } from '../lib/format'
import { riskOf } from '../lib/simulation'
import FullscreenPanel from './FullscreenPanel'
import Card from './Card'
import { Badge } from './Badge'
import type { Cell } from '../types'

type Point = { x: number; y: number; z?: number }
const palette: Record<string, string> = { SAFE: '#173b36', CAUTION: '#5c5424', WARNING: '#694124', CRITICAL: '#702d36' }

/** Lightweight perspective renderer: every cell, marker, and route shares the backend grid coordinates. */
export default function Map3D({ mode }: { mode: 'live' | 'route' }) {
  const { w, live, backend, setDestination } = useDashboard()
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const viewRef = useRef({ yaw: -0.62, pitch: 0.72, zoom: 1, panX: 0, panY: 0 })
  const [revision, setRevision] = useState(0)
  const [dragging, setDragging] = useState(false)
  const drag = useRef<{ x: number; y: number; startX: number; startY: number; button: number; moved: boolean } | null>(null)
  const map = live ? backend.map : null
  const rows = map?.rows ?? w.size, cols = map?.columns ?? w.size
  const cells = map?.cells
  const simulatedRisk = riskOf(w)
  const trail = map?.odometryAvailable ? map.odometryPath : []
  const rover: Point = trail.length ? { x: trail[trail.length - 1].x, y: trail[trail.length - 1].y } : { x: (map?.rover.column ?? w.rover.c) + .5, y: (map?.rover.row ?? w.rover.r) + .5 }
  const heading = map?.odometryHeadingRad ?? (map ? (map.rover.heading === 'E' ? 0 : map.rover.heading === 'S' ? Math.PI / 2 : map.rover.heading === 'W' ? Math.PI : -Math.PI / 2) : w.rover.h * Math.PI / 2 - Math.PI / 2)
  const routeCells: Cell[] = w.route.found && (!live || w.route.planner === 'backend') ? w.route.path : []
  const goalText = live ? (map?.goal ?? backend.status?.goal) : null
  const goal = (goalText ? parseCell(goalText) : null) ?? w.goal
  const scoreAt = (r: number, c: number) => cells ? cells[r * cols + c]?.riskScore ?? 0 : simulatedRisk[r]?.[c] ?? 0
  const obstacleAt = (r: number, c: number) => cells ? !!cells[r * cols + c]?.isObstacle : !!w.obs[r]?.[c]

  const draw = useCallback(() => {
    const canvas = canvasRef.current, ctx = canvas?.getContext('2d')
    if (!canvas || !ctx) return
    const rect = canvas.getBoundingClientRect(), dpr = Math.min(window.devicePixelRatio || 1, 2)
    canvas.width = Math.max(1, rect.width * dpr); canvas.height = Math.max(1, rect.height * dpr)
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
    const W = rect.width, H = rect.height, v = viewRef.current
    ctx.fillStyle = '#08121b'; ctx.fillRect(0, 0, W, H)
    const span = Math.max(rows, cols), scale = Math.min(W, H) / (span * 1.7) * v.zoom
    const cy = Math.cos(v.yaw), sy = Math.sin(v.yaw), cp = Math.cos(v.pitch), sp = Math.sin(v.pitch)
    const project = (p: Point) => {
      const x = p.x - cols / 2, y = p.y - rows / 2, z = p.z ?? 0
      const a = x * cy - y * sy, b = x * sy + y * cy
      return { x: W / 2 + v.panX + a * scale, y: H * .48 + v.panY + (b * cp - z * sp) * scale, d: b * sp + z * cp }
    }
    const poly = (pts: Point[], fill: string, stroke = '#253847') => { const pp = pts.map(project); ctx.beginPath(); pp.forEach((p, i) => i ? ctx.lineTo(p.x, p.y) : ctx.moveTo(p.x, p.y)); ctx.closePath(); ctx.fillStyle = fill; ctx.fill(); ctx.strokeStyle = stroke; ctx.lineWidth = .7; ctx.stroke() }
    const line = (pts: Point[], color: string, width: number, dash: number[] = []) => { if (pts.length < 2) return; ctx.beginPath(); pts.map(project).forEach((p, i) => i ? ctx.lineTo(p.x, p.y) : ctx.moveTo(p.x, p.y)); ctx.strokeStyle = color; ctx.lineWidth = width; ctx.setLineDash(dash); ctx.stroke(); ctx.setLineDash([]) }
    // Ground grid
    for (let x = 0; x <= cols; x++) line([{ x, y: 0 }, { x, y: rows }], '#233847', 1)
    for (let y = 0; y <= rows; y++) line([{ x: 0, y }, { x: cols, y }], '#233847', 1)
    // Sort raised cells by depth to keep nearby blocks in front.
    const blocks: { r: number; c: number; depth: number }[] = []
    for (let r = 0; r < rows; r++) for (let c = 0; c < cols; c++) if (obstacleAt(r, c) || scoreAt(r, c) >= 35) blocks.push({ r, c, depth: project({ x: c + .5, y: r + .5 }).d })
    blocks.sort((a, b) => a.depth - b.depth)
    for (const { r, c } of blocks) {
      const obstacle = obstacleAt(r, c), level = levelFromScore(scoreAt(r, c)), z = obstacle ? .72 : .16
      const color = obstacle ? '#718398' : palette[level]
      poly([{ x: c, y: r, z }, { x: c + 1, y: r, z }, { x: c + 1, y: r + 1, z }, { x: c, y: r + 1, z }], color)
      if (obstacle) {
        poly([{ x: c + 1, y: r, z: 0 }, { x: c + 1, y: r + 1, z: 0 }, { x: c + 1, y: r + 1, z }, { x: c + 1, y: r, z }], '#42566b')
        poly([{ x: c, y: r + 1, z: 0 }, { x: c + 1, y: r + 1, z: 0 }, { x: c + 1, y: r + 1, z }, { x: c, y: r + 1, z }], '#53687d')
      }
    }
    // Planned route and encoder-only travelled trail remain distinct.
    line(routeCells.map(c => ({ x: c.c + .5, y: c.r + .5, z: .22 })), '#29b6f6', 4)
    if (trail.length > 1) line(trail.map(p => ({ x: p.x, y: p.y, z: .3 })), '#c084fc', 3)
    const fires = cells?.filter(c => c.isFire).map(c => ({ x: c.column + .5, y: c.row + .5 })) ?? []
    fires.forEach(p => { const q = project({ ...p, z: .24 }); ctx.beginPath(); ctx.arc(q.x, q.y, Math.max(5, scale * .24), 0, Math.PI * 2); ctx.strokeStyle = '#fb923c'; ctx.lineWidth = 2; ctx.stroke() })
    const people = cells?.filter(c => c.isPerson).map(c => ({ x: c.column + .5, y: c.row + .5 })) ?? (!live ? w.persons.map(p => ({ x: p.c + .5, y: p.r + .5 })) : [])
    people.forEach(p => { const q = project({ ...p, z: .52 }); ctx.beginPath(); ctx.arc(q.x, q.y, Math.max(4, scale * .12), 0, Math.PI * 2); ctx.fillStyle = '#f472b6'; ctx.fill() })
    if (goal) { const q = project({ x: goal.c + .5, y: goal.r + .5, z: .25 }); ctx.beginPath(); ctx.arc(q.x, q.y, Math.max(8, scale * .22), 0, Math.PI * 2); ctx.fillStyle = '#22c55e'; ctx.fill(); ctx.strokeStyle = '#dcfce7'; ctx.lineWidth = 2; ctx.stroke() }
    // Screen-space top-down rover glyph stays legible across map zoom levels.
    const center = project({ x: rover.x, y: rover.y, z: .58 })
    const nose = project({ x: rover.x + Math.cos(heading) * .5, y: rover.y + Math.sin(heading) * .5, z: .58 })
    const iconAngle = Math.atan2(nose.y - center.y, nose.x - center.x)
    const radius = Math.max(9, Math.min(15, scale * .42))
    ctx.save(); ctx.translate(center.x, center.y); ctx.rotate(iconAngle)
    ctx.beginPath(); ctx.arc(0, 0, radius + 3, 0, Math.PI * 2); ctx.fillStyle = '#07131d'; ctx.fill()
    ctx.strokeStyle = map?.odometryAvailable ? '#22d3ee' : live ? '#fbbf24' : '#38bdf8'; ctx.lineWidth = 2.5; ctx.stroke()
    ctx.fillStyle = '#111827'
    for (const wx of [-1, 1]) for (const wy of [-1, 1]) ctx.fillRect(wx * radius * .27 - radius * .12, wy * radius * .4 - radius * .12, radius * .24, radius * .24)
    ctx.fillStyle = '#e0f2fe'; ctx.fillRect(-radius * .2, -radius * .45, radius * .4, radius * .9)
    ctx.beginPath(); ctx.moveTo(radius * .48, 0); ctx.lineTo(radius * .2, -radius * .2); ctx.lineTo(radius * .2, radius * .2); ctx.closePath(); ctx.fillStyle = '#22d3ee'; ctx.fill()
    ctx.restore()
    ctx.fillStyle = '#e2e8f0'; ctx.font = 'bold 10px ui-monospace, monospace'
    const roverLabel = live
      ? `ROVER ${map ? cellName(map.rover.row, map.rover.column) : ''} ${map?.rover.heading ?? ''} · ${map?.odometryAvailable ? 'ENCODER POSITION' : 'ESTIMATED POSITION'}`
      : 'ROVER · SIMULATED'
    ctx.fillText(roverLabel, 12, H - 12)
  }, [cols, rows, trail, routeCells, cells, goal?.r, goal?.c, rover.x, rover.y, heading, revision, w, live])
  useEffect(() => { draw(); const el = canvasRef.current; if (!el) return; const ro = new ResizeObserver(draw); ro.observe(el); return () => ro.disconnect() }, [draw])
  const reset = () => { viewRef.current = { yaw: -.62, pitch: .72, zoom: 1, panX: 0, panY: 0 }; setRevision(x => x + 1) }
  const onDown = (e: React.PointerEvent<HTMLCanvasElement>) => { drag.current = { x: e.clientX, y: e.clientY, startX: e.clientX, startY: e.clientY, button: e.button, moved: false }; e.currentTarget.setPointerCapture(e.pointerId); setDragging(true) }
  const onMove = (e: React.PointerEvent<HTMLCanvasElement>) => { if (!drag.current) return; const dx = e.clientX - drag.current.x, dy = e.clientY - drag.current.y; drag.current = { ...drag.current, x: e.clientX, y: e.clientY, moved: drag.current.moved || Math.hypot(e.clientX - drag.current.startX, e.clientY - drag.current.startY) > 5 }; if (drag.current.button === 2 || e.shiftKey) { viewRef.current.panX += dx; viewRef.current.panY += dy } else { viewRef.current.yaw += dx * .008; viewRef.current.pitch = Math.max(.18, Math.min(1.35, viewRef.current.pitch + dy * .006)) } setRevision(x => x + 1) }
  const onUp = (e: React.PointerEvent<HTMLCanvasElement>) => {
    const current = drag.current
    if (mode === 'route' && current && !current.moved && live && map) {
      const rect = e.currentTarget.getBoundingClientRect(), v = viewRef.current
      const scale = Math.min(rect.width, rect.height) / (Math.max(rows, cols) * 1.7) * v.zoom
      const sx = (e.clientX - rect.left - rect.width / 2 - v.panX) / scale
      const sy = (e.clientY - rect.top - rect.height * .48 - v.panY) / scale
      const cy = Math.cos(v.yaw), syaw = Math.sin(v.yaw), cp = Math.cos(v.pitch)
      const x = cols / 2 + cy * sx + syaw * sy / cp
      const y = rows / 2 - syaw * sx + cy * sy / cp
      const r = Math.floor(y), c = Math.floor(x)
      if (r >= 0 && r < rows && c >= 0 && c < cols) void setDestination({ r, c })
    }
    drag.current = null; setDragging(false)
  }
  return <FullscreenPanel><Card title={mode === 'live' ? '3D live exploration map' : '3D route planning map'} right={<Badge kind={map?.odometryAvailable ? 'live' : live ? 'warn' : 'sim'}>{map?.odometryAvailable ? 'ENCODER ODOMETRY' : live ? 'LIVE MAP' : 'SIMULATION'}</Badge>} className="h-full">
    <div className="relative">
      <canvas ref={canvasRef} aria-label="Interactive three-dimensional rover map" className={`h-[340px] w-full touch-none rounded-md border border-slate-700 ${dragging ? 'cursor-grabbing' : mode === 'route' ? 'cursor-crosshair' : 'cursor-grab'}`} onPointerDown={onDown} onPointerMove={onMove} onPointerUp={onUp} onPointerCancel={() => { drag.current = null; setDragging(false) }} onContextMenu={e => e.preventDefault()} onWheel={e => { viewRef.current.zoom = Math.max(.55, Math.min(3, viewRef.current.zoom * (e.deltaY > 0 ? .9 : 1.1))); setRevision(x => x + 1) }} />
      <div className="absolute bottom-3 right-3 flex gap-1">
        <button onClick={() => { viewRef.current.zoom = Math.max(.55, viewRef.current.zoom / 1.15); setRevision(x => x + 1) }} title="Zoom out" aria-label="Zoom out" className="rounded border border-slate-600 bg-slate-900 p-2 text-slate-200"><Minus size={15} /></button>
        <button onClick={() => { viewRef.current.zoom = Math.min(3, viewRef.current.zoom * 1.15); setRevision(x => x + 1) }} title="Zoom in" aria-label="Zoom in" className="rounded border border-slate-600 bg-slate-900 p-2 text-slate-200"><Plus size={15} /></button>
        <button onClick={reset} title="Reset camera" aria-label="Reset camera" className="rounded border border-slate-600 bg-slate-900 p-2 text-slate-200"><RotateCcw size={15} /></button>
      </div>
      {mode === 'route' && !goal && <div className="pointer-events-none absolute inset-x-3 top-3 rounded bg-slate-950/85 px-3 py-2 text-center text-sm text-slate-200">Select a destination to generate a route.</div>}
      {mode === 'route' && live && <div className="pointer-events-none absolute inset-x-3 bottom-10 rounded bg-slate-950/85 px-3 py-1.5 text-center text-xs text-slate-300">Click a map cell to set the live route destination.</div>}
      <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-400"><span>Drag: orbit</span><span>Shift+drag / right drag: pan</span><span>Wheel or +/−: zoom</span><span className="text-emerald-300">Green: destination</span><span className="text-sky-300">Blue: planned route</span><span className="text-violet-300">Violet: encoder trail</span><span className="text-amber-300">Amber rover: estimated pose</span></div>
    </div>
  </Card></FullscreenPanel>
}
