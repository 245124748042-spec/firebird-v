import { ReactNode } from 'react'
export default function Card({ title, icon, right, children, className = '' }: { title: string; icon?: ReactNode; right?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={`rounded-lg border border-line bg-panel ${className}`}>
      <header className="flex items-center justify-between gap-2 border-b border-line px-4 py-2.5">
        <h2 className="flex items-center gap-2 text-sm font-semibold text-slate-900">{icon}{title}</h2>{right}
      </header>
      <div className="p-4">{children}</div>
    </section>
  )
}
