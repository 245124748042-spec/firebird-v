import { useDashboard } from '../hooks/useDashboard'
import { clearMap, resizeWorld } from '../lib/simulation'
import Button from './Button'
import Card from './Card'

const TOOLS: [string, string][] = [['select', 'Cell details'], ['start', 'Set Start Position'], ['obstacle', 'Add Obstacle'], ['unobstacle', 'Remove Obstacle'], ['person', 'Add Simulated Person'], ['hotspot', 'Add Simulated Hotspot']]

export default function Controls() {
  const { w, act } = useDashboard()
  return (
    <Card title="Map tools">
      <div className="flex flex-wrap gap-2">
        {TOOLS.map(([id, l]) => <Button key={id} active={w.tool === id} onClick={() => act(x => (x.tool = id))}>{l}</Button>)}
        <Button kind="danger" onClick={() => act(clearMap)}>Clear Map</Button>
      </div>
      <p className="mt-2 text-xs text-slate-500">Pick a tool, then click a cell. In Simulation mode, set the green source and red destination directly on the 3D route map.</p>
      <label className="mt-3 block text-sm text-slate-800">Grid size: <span className="font-mono">{w.size} x {w.size}</span>
        <input type="range" min={5} max={20} value={w.size} onChange={e => act(x => resizeWorld(x, +e.target.value))} className="mt-1 w-full" aria-label="Grid size" /></label>
    </Card>
  )
}
