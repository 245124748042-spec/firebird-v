import { ReactNode } from 'react'
const tone = { ok: 'text-ok', warn: 'text-ember', crit: 'text-alarm', info: 'text-scan', gray: 'text-slate-800' }
export type Tone = keyof typeof tone
export const toneClass = tone
export default function MetricTile({ label, value, sub, t = 'gray' }: { label: string; value: ReactNode; sub?: ReactNode; t?: Tone }) {
  return (
    <div className="rounded-md border border-line bg-base/60 p-3">
      <div className="text-xs text-slate-600">{label}</div>
      <div className={`mt-0.5 font-mono text-lg font-medium ${tone[t]}`}>{value}</div>
      {sub && <div className="text-xs text-slate-500">{sub}</div>}
    </div>
  )
}
