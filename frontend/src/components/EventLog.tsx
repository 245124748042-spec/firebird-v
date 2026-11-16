import { ScrollText } from 'lucide-react'
import { useDashboard } from '../hooks/useDashboard'
import { fmtTime } from '../lib/format'
import Card from './Card'

const dot = { Info: 'bg-scan', Warning: 'bg-ember', Critical: 'bg-alarm' }
export default function EventLog({ limit = 14 }: { limit?: number }) {
  const { allEvents } = useDashboard()
  return (
    <Card title="Live activity timeline" icon={<ScrollText size={16} />}>
      <ul className="max-h-72 space-y-1.5 overflow-y-auto pr-1 text-sm">
        {allEvents.slice(0, limit).map(e => (
          <li key={e.id} className="flex gap-2"><span className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${dot[e.severity]}`} />
            <span className="pt-0.5 font-mono text-xs text-slate-500">{fmtTime(e.t)}</span><span className="text-slate-700">{e.event}</span></li>))}
      </ul>
    </Card>
  )
}
