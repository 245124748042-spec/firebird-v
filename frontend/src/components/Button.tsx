import { ReactNode } from 'react'
export default function Button({ onClick, children, active, kind = 'default', disabled, title }: { onClick?: () => void; children: ReactNode; active?: boolean; kind?: 'default' | 'primary' | 'danger'; disabled?: boolean; title?: string }) {
  return (
    <button onClick={onClick} disabled={disabled} title={title} aria-pressed={active}
      className={`inline-flex items-center justify-center gap-1.5 rounded-md border px-3 py-1.5 text-sm disabled:opacity-40 ${kind === 'primary' ? 'border-ember bg-ember font-semibold text-slate-900 hover:bg-amber-400' : kind === 'danger' ? 'border-alarm/60 text-alarm hover:bg-alarm/10' : active ? 'border-scan bg-scan/10 text-scan' : 'border-line bg-base text-slate-800 hover:border-slate-500'}`}>{children}</button>
  )
}
