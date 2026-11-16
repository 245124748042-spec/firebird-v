import { ReactNode } from 'react'
import { Radio, FlaskConical } from 'lucide-react'
import { useDashboard } from '../hooks/useDashboard'
import type { DataSource } from '../types'

const kinds = {
  sim: 'border-ember/60 bg-ember/10 text-ember', live: 'border-ok/60 bg-ok/10 text-ok', ok: 'border-ok/50 bg-ok/10 text-ok', warn: 'border-ember/60 bg-ember/10 text-ember',
  crit: 'border-alarm/60 bg-alarm/10 text-alarm', info: 'border-scan/50 bg-scan/10 text-scan', gray: 'border-line bg-base text-slate-600'
}
export type BadgeKind = keyof typeof kinds
export const Badge = ({ kind = 'gray', children }: { kind?: BadgeKind; children: ReactNode }) =>
  <span className={`inline-flex items-center rounded border px-1.5 py-0.5 text-[11px] font-semibold ${kinds[kind]}`}>{children}</span>
export const SourceBadge = ({ live, source }: { live: boolean; source?: DataSource }) => live
  ? <Badge kind="live">{source === 'LIVE_PI' ? 'LIVE RASPBERRY PI' : 'LIVE SERIAL'}</Badge>
  : source === 'LIVE_PI' ? <Badge kind="warn">LAST REAL READING - PI DISCONNECTED</Badge>
    : source === 'LIVE_SERIAL' ? <Badge kind="warn">LAST REAL READING - DISCONNECTED</Badge>
      : <Badge kind="sim">SIMULATED</Badge>
export const NoticeBox = ({ kind, children }: { kind: 'warn' | 'crit' | 'info' | 'ok'; children: ReactNode }) =>
  <div role="status" className={`rounded-md border px-4 py-2 text-sm ${kinds[kind]}`}>{children}</div>

export function ModeBadge() {
  const { live, backend } = useDashboard()
  const pi = backend.status?.raspberryPi
  return live
    ? <span role="status" className="flex items-center gap-1.5 rounded-md border border-ok/60 bg-ok/10 px-3 py-1.5 text-xs font-semibold text-ok"><Radio size={14} />LIVE MODE - FireBird connected on {backend.telemetry?.source === 'LIVE_PI' ? 'Raspberry Pi Wi-Fi' : backend.status?.serial.port ?? 'serial port'}</span>
    : <span role="status" className="flex items-center gap-1.5 rounded-md border border-ember/60 bg-ember/10 px-3 py-1.5 text-xs font-semibold text-ember"><FlaskConical size={14} />{pi?.enabled ? pi.connected ? 'RASPBERRY PI CONNECTED - AWAITING VALID TELEMETRY' : 'RASPBERRY PI DISCONNECTED - SIMULATION MODE' : 'SIMULATION MODE - No live robot connected'}</span>
}
