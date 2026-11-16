import type { Cell, EventRec, FireBirdTelemetry, Movement, RiskLevel } from '../types'

export const cellName = (r: number, c: number) => String.fromCharCode(65 + r) + (c + 1)
export function parseCell(s: string): Cell | null {
  const m = /^([A-T])(\d{1,2})$/.exec(s.trim().toUpperCase())
  return m ? { r: m[1].charCodeAt(0) - 65, c: +m[2] - 1 } : null
}
// Alert thresholds. Smoke is the raw sensor value (SM). Calibrate for your sensor.
export const TEMP_WARN = 40, TEMP_CRIT = 55, SMOKE_WARN = 300, SMOKE_CRIT = 600

export const levelFromScore = (s: number): RiskLevel => (s < 15 ? 'SAFE' : s < 45 ? 'CAUTION' : s < 70 ? 'WARNING' : 'CRITICAL')
export const levelLabel: Record<RiskLevel, string> = { SAFE: 'Low', CAUTION: 'Moderate', WARNING: 'High', CRITICAL: 'Critical' }
export const levelTone = (l: RiskLevel): 'ok' | 'warn' | 'crit' => (l === 'SAFE' ? 'ok' : l === 'CAUTION' || l === 'WARNING' ? 'warn' : 'crit')

export const MOVE_WORD: Record<Movement, string> = { F: 'FORWARD', B: 'BACKWARD', L: 'LEFT', R: 'RIGHT', S: 'STOP' }
export const rawLine = (t: FireBirdTelemetry) =>
  `L:${t.leftIr},C:${t.centerIr},R:${t.rightIr},T:${t.temperatureTenths},H:${t.humidityTenths},SM:${t.smokeValue},OBS:${t.obstacleDetected ? 1 : 0},MOVE:${t.movement},RISK:${t.riskScore},PC:${t.personCount}`
export const fmtTime = (v: number | string) => new Date(v).toLocaleTimeString()

export function toCsv(events: EventRec[], log: { t: number; src: string; raw: string }[]) {
  const q = (s: string) => `"${s.replace(/"/g, '""')}"`
  const a = ['section,time,source,severity,module,event,grid,action,status', ...events.map(e => ['alert', new Date(e.t).toISOString(), e.source, e.severity, e.module, q(e.event), e.cell, q(e.action), e.status].join(','))]
  const t = log.map(l => ['telemetry', new Date(l.t).toISOString(), l.src, '', '', q(l.raw), '', '', ''].join(','))
  return [...a, ...t].join('\n')
}
