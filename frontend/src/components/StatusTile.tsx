import { ReactNode } from 'react'
import { toneClass, Tone } from './MetricTile'
export default function StatusTile({ icon, title, value, sub, t, badge }: { icon: ReactNode; title: string; value: string; sub: ReactNode; t: Tone; badge: ReactNode }) {
  return (
    <div className="rounded-lg border border-line bg-panel p-4">
      <div className="flex items-center justify-between gap-2 text-sm text-slate-600"><span className="flex items-center gap-2">{icon}{title}</span>{badge}</div>
      <div className={`mt-3 font-mono text-2xl ${toneClass[t]}`}>{value}</div>
      <div className="mt-1 font-mono text-xs text-slate-500">{sub}</div>
    </div>
  )
}
