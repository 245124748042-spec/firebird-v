import { Activity, ChevronRight, Flame, LayoutDashboard, Route, Thermometer, Users } from 'lucide-react'
import { ModeBadge } from './Badge'

const features = [
  { icon: Activity, title: 'Obstacle avoidance telemetry', text: 'Left, center, right and side distances, obstacle flag and movement state from FireBird.' },
  { icon: Route, title: 'RAIR-inspired A* route planning', text: 'Risk-aware routes with an adjustable risk attitude, compared against the shortest route.' },
  { icon: Users, title: 'YOLO person detection and count', text: 'Laptop-camera person count, stabilized over 3 frames and sent to FireBird.' },
  { icon: Thermometer, title: 'Environmental and fire-risk monitoring', text: 'Temperature, humidity and smoke readings turned into a live fire-risk level and map.' }
]
const demos: [string, string][] = [['Normal patrol', 'Rover idle on a clear map.'], ['Obstacle avoidance', 'Add an obstacle on the route: the rover stops, marks the cell and replans.'], ['A* route following', 'Calculate a route and watch the rover follow the command queue.'], ['Person detection', 'Add a simulated person and choose Ignore, Slow down or Stop.'], ['Thermal hotspot', 'Heat Hotspot scenario raises risk to orange.'], ['Confirmed fire', 'Confirmed Fire scenario turns nearby cells red.'], ['Person near fire', 'A person next to red or orange cells raises a critical alert.']]
const stage: [string, boolean][] = [['FireBird obstacle-avoidance logic developed', true], ['DHT22 and smoke sensors connected', true], ['Trained YOLO person-detection model available', true], ['PC RAIR/A* planner integration planned', false], ['Real serial hardware integration pending', false]]
const roadmap = ['Dashboard simulation', 'FireBird serial telemetry', 'Laptop-camera YOLO person detection', 'A* route following', 'Environmental/fire-risk integration', 'RAIR-inspired risk-aware replanning', 'Full autonomous hazard mapping']

const risk = (r: number, c: number) => 100 * Math.exp(-((r - 3) ** 2 + (c - 7) ** 2) / 3)
const col = (v: number) => (v < 15 ? '#bbf7d0' : v < 45 ? '#fde047' : v < 70 ? '#fdba74' : '#f87171')
function Preview() {
  return (
    <svg viewBox="0 0 10 10" className="w-full rounded-lg border border-line bg-white shadow-sm" role="img" aria-label="Preview of grid map with rover, obstacles, a person, a fire hotspot and a blue route">
      {Array.from({ length: 100 }, (_, i) => { const r = Math.floor(i / 10), c = i % 10; return <rect key={i} x={c} y={r} width={1} height={1} fill={col(risk(r, c))} stroke="#fff" strokeWidth={0.05} /> })}
      {[[2, 2], [2, 3], [5, 5], [6, 5]].map(([r, c]) => <rect key={`${r}${c}`} x={c} y={r} width={1} height={1} fill="#94a3b8" stroke="#fff" strokeWidth={0.05} />)}
      <polyline points="0.5,9.5 0.5,6.5 3.5,6.5 3.5,3.5 4.5,3.5 4.5,0.5 8.5,0.5" fill="none" stroke="#0284c7" strokeWidth={0.18} strokeLinejoin="round" />
      <circle cx={7.5} cy={3.5} r={0.3} fill="none" stroke="#b45309" strokeWidth={0.1} /><circle cx={6.5} cy={8.5} r={0.22} fill="#0f172a" />
      <circle cx={8.5} cy={0.5} r={0.38} fill="#fff" stroke="#0284c7" strokeWidth={0.12} /><polygon points="0.5,9.1 0.8,9.8 0.2,9.8" fill="#0284c7" stroke="#0c4a6e" strokeWidth={0.06} />
    </svg>
  )
}

export default function Home({ onOpen }: { onOpen: () => void }) {
  return (
    <div className="min-h-screen">
      <div className="border-b border-line bg-panel"><div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-3 px-6 py-3">
        <div className="flex items-center gap-2 font-semibold text-slate-900"><Flame size={20} className="text-ember" />FireBird</div><ModeBadge />
      </div></div>
      <main className="mx-auto max-w-6xl px-6">
        <section className="grid items-center gap-10 py-12 lg:grid-cols-2">
          <div>
            <h1 className="text-4xl font-semibold leading-tight text-slate-900 sm:text-5xl">Find hazards and plan safer routes before people have to.</h1>
            <p className="mt-4 text-lg text-slate-700">FireBird: AI-Based Autonomous Hazard Detection and Dynamic Risk Mapping Rover</p>
            <p className="mt-2 max-w-prose text-sm text-slate-600">All data is simulated until the robot is connected through the Python backend. The dashboard switches to LIVE MODE only when the backend confirms an open serial connection and real telemetry arrives.</p>
            <button onClick={onOpen} className="mt-7 flex items-center gap-2 rounded-md bg-ember px-5 py-3 text-sm font-semibold text-slate-900 hover:bg-amber-400"><LayoutDashboard size={18} />Open Dashboard<ChevronRight size={16} /></button>
          </div>
          <div><Preview /><p className="mt-2 text-xs text-slate-600">Static preview: rover, obstacles, a person, a fire hotspot with fading risk cells and a blue route.</p></div>
        </section>
        <section className="pb-10"><h2 className="mb-4 text-xl font-semibold text-slate-900">What the dashboard shows</h2>
          <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">{features.map(({ icon: I, title, text }) => <li key={title} className="rounded-lg border border-line bg-panel p-4"><I size={22} className="text-scan" /><h3 className="mt-3 font-semibold text-slate-900">{title}</h3><p className="mt-1 text-sm text-slate-600">{text}</p></li>)}</ul></section>
        <section className="pb-10"><h2 className="mb-4 text-xl font-semibold text-slate-900">Demo scenarios</h2>
          <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">{demos.map(([t, d]) => <li key={t} className="rounded-lg border border-line bg-panel p-3"><div className="text-sm font-semibold text-slate-900">{t}</div><div className="text-sm text-slate-600">{d}</div></li>)}</ul></section>
        <section className="grid gap-6 pb-12 md:grid-cols-2">
          <div><h2 className="mb-3 text-xl font-semibold text-slate-900">Current project stage</h2>
            <ul className="space-y-2">{stage.map(([t, done]) => <li key={t} className="flex items-center gap-2 text-sm text-slate-700"><span className={`h-2.5 w-2.5 rounded-full ${done ? 'bg-ok' : 'bg-ember'}`} />{t}<span className="text-xs text-slate-500">{done ? '(done)' : '(pending)'}</span></li>)}</ul></div>
          <div><h2 className="mb-3 text-xl font-semibold text-slate-900">Future roadmap</h2>
            <ol className="space-y-2">{roadmap.map((t, i) => <li key={t} className="text-sm text-slate-700"><span className="font-mono text-xs text-slate-500">Phase {i + 1}</span> {t}</li>)}</ol></div>
        </section>
      </main>
      <footer className="border-t border-line bg-panel py-5 text-center text-xs text-slate-600">Final-year engineering project. Prototype only, not a certified safety system.</footer>
    </div>
  )
}
