import { useState } from 'react'
import { Download } from 'lucide-react'
import { useDashboard } from '../hooks/useDashboard'
import { fmtTime, toCsv } from '../lib/format'
import Button from './Button'
import Card from './Card'
import { EventFrequencyChart } from './Charts'
import { Badge, SourceBadge } from './Badge'

const FILTERS = ['All', 'Info', 'Warning', 'Critical', 'Obstacle', 'Person', 'Path', 'Environment', 'System']

export default function TelemetryConsole() {
  const { w, live, backend, allEvents, ackAll, clearNoncritical } = useDashboard()
  const [f, setF] = useState('All')
  const rows = allEvents.filter(e => f === 'All' || e.severity === f || e.module === f)
  const data = ['Obstacle', 'Person', 'Path', 'Environment', 'System'].map(m => ({ module: m, count: allEvents.filter(e => e.module === m).length }))
  const retainedPi = backend.status?.raspberryPi?.enabled && w.tel.source === 'LIVE_PI'
  const lines = w.telLog.filter(l => retainedPi ? l.src === 'LIVE_PI' : (live ? l.src !== 'SIMULATED' : l.src === 'SIMULATED'))
  const exportCsv = () => {
    const a = document.createElement('a')
    a.href = URL.createObjectURL(new Blob([toCsv(allEvents, w.telLog)], { type: 'text/csv' }))
    a.download = `firebird-log-${Date.now()}.csv`; a.click(); URL.revokeObjectURL(a.href)
  }
  const s = backend.status?.serial
  return (
    <>
      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Serial console" right={<SourceBadge live={live} source={w.tel.source} />}>
          <p className="mb-2 text-xs text-slate-600">{backend.status?.raspberryPi?.enabled ? `Raspberry Pi Wi-Fi: ${backend.status.raspberryPi.connected ? 'connected' : 'disconnected'}` : `Serial: ${s?.connected ? `connected on ${s.port} @ ${s.baudRate}` : 'not connected'}`} | Last received: {backend.telemetryAt ? fmtTime(backend.telemetryAt) : 'never'}</p>
          <ul className="h-52 space-y-0.5 overflow-y-auto rounded bg-slate-900 p-2 font-mono text-xs text-slate-100">
            {lines.map((l, i) => <li key={i}><span className="text-slate-400">{fmtTime(l.t)} </span>{l.src === 'SIMULATED' ? '[SIMULATED] ' : l.src === 'PC to FIREBIRD' ? 'TX> ' : ''}{l.raw}</li>)}
            {lines.length === 0 && <li className="text-slate-400">{retainedPi ? 'Waiting for the next Raspberry Pi frame...' : live ? 'Waiting for telemetry messages...' : 'Waiting for simulated telemetry...'}</li>}
          </ul>
          <p className="mt-2 font-mono text-[11px] text-slate-500">FireBird: $FB,ms,ir1,ir2,ir3,ir4,ir5,temp_x10,hum_x10,smoke,env_risk,total_risk,persons,dir,speed,dht_ok,flags</p>
        </Card>
        <Card title="Event frequency by module"><EventFrequencyChart data={data} /></Card>
      </div>
      <Card title="Alerts and events" right={<div className="flex flex-wrap gap-2"><Button onClick={ackAll}>Acknowledge Alert</Button><Button onClick={clearNoncritical}>Clear Noncritical Alerts</Button><Button onClick={exportCsv}><Download size={14} />Export CSV</Button></div>}>
        <div className="mb-3 flex flex-wrap gap-1">{FILTERS.map(x => <Button key={x} active={f === x} onClick={() => setF(x)}>{x}</Button>)}</div>
        <div className="max-h-96 overflow-auto"><table className="w-full text-left text-sm"><thead className="sticky top-0 bg-panel text-xs text-slate-600"><tr>
          {['Time', 'Severity', 'Module', 'Event', 'Grid Location', 'Recommended Action', 'Status'].map(h => <th key={h} className="px-2 py-1.5 font-medium">{h}</th>)}</tr></thead>
          <tbody>{rows.map(e => <tr key={e.id} className="border-t border-line">
            <td className="px-2 py-1.5 font-mono text-xs">{fmtTime(e.t)}</td>
            <td className="px-2"><Badge kind={e.severity === 'Critical' ? 'crit' : e.severity === 'Warning' ? 'warn' : 'info'}>{e.severity}</Badge></td>
            <td className="px-2">{e.module}</td>
            <td className="px-2">{e.event} <Badge kind={e.source === 'SIMULATED' ? 'sim' : 'live'}>{e.source === 'SIMULATED' ? 'SIMULATED' : 'LIVE'}</Badge></td>
            <td className="px-2 font-mono">{e.cell}</td><td className="px-2 text-slate-600">{e.action}</td><td className="px-2">{e.status}</td></tr>)}</tbody></table></div>
      </Card>
    </>
  )
}

