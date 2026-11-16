import { useDashboard } from '../hooks/useDashboard'
import { levelFromScore, levelLabel, levelTone, SMOKE_CRIT, SMOKE_WARN, TEMP_CRIT, TEMP_WARN } from '../lib/format'
import { envOf, SC, SCENARIO_LIST, scenarioCell, setScenario, World } from '../lib/simulation'
import { cellName } from '../lib/format'
import Button from './Button'
import Card from './Card'
import { MetricLineChart } from './Charts'
import MetricTile from './MetricTile'
import { Badge, NoticeBox, SourceBadge } from './Badge'

const STOPS: [number, number[]][] = [[0, [76, 29, 149]], [0.2, [37, 99, 235]], [0.4, [22, 163, 74]], [0.55, [234, 179, 8]], [0.75, [234, 88, 12]], [0.9, [220, 38, 38]], [1, [255, 255, 255]]]
const heat = (t: number) => {
  const x = Math.max(0, Math.min(1, (t - 20) / 180))
  for (let i = 1; i < STOPS.length; i++) if (x <= STOPS[i][0]) {
    const [a, ca] = STOPS[i - 1], [b, cb] = STOPS[i], f = (x - a) / (b - a)
    return `rgb(${ca.map((v, j) => Math.round(v + (cb[j] - v) * f)).join(',')})`
  }
  return '#fff'
}

function Gauge({ score }: { score: number }) {
  const a = Math.PI * (1 - Math.max(0, Math.min(100, score)) / 100)
  const arc = (from: number, to: number, color: string) => {
    const p = (v: number) => { const t = Math.PI * (1 - v / 100); return `${100 + 80 * Math.cos(t)} ${100 - 80 * Math.sin(t)}` }
    return <path d={`M ${p(from)} A 80 80 0 0 1 ${p(to)}`} fill="none" stroke={color} strokeWidth={16} />
  }
  return (
    <svg viewBox="0 0 200 120" className="mx-auto w-56" role="img" aria-label={`Fire-risk gauge ${score} of 100`}>
      {arc(0, 15, '#86efac')}{arc(15, 45, '#fde047')}{arc(45, 70, '#fdba74')}{arc(70, 100, '#f87171')}
      <line x1={100} y1={100} x2={100 + 62 * Math.cos(a)} y2={100 - 62 * Math.sin(a)} stroke="#0f172a" strokeWidth={3} strokeLinecap="round" />
      <circle cx={100} cy={100} r={6} fill="#0f172a" />
      <text x={100} y={118} textAnchor="middle" fontSize={14} className="font-mono" fill="#0f172a">{score}/100</text>
    </svg>
  )
}

function evidence(w: World, real: boolean, live: boolean) {
  const e = envOf(w)
  const lv = (v: number, warn: number, crit: number, u: string) => (v >= crit ? `at or above ${crit}${u}: critical` : v >= warn ? `at or above ${warn}${u}: caution` : 'normal range')
  const list = [
    `Temperature ${e.temp.toFixed(1)} Â°C (${lv(e.temp, TEMP_WARN, TEMP_CRIT, ' Â°C')})`,
    `Smoke value ${e.smoke} (${lv(e.smoke, SMOKE_WARN, SMOKE_CRIT, '')})`,
    `Humidity ${e.hum.toFixed(1)} %`,
    `Reported risk score ${e.score}/100${real ? live ? ' (current FireBird reading)' : ' (last real FireBird reading)' : ' (simulated)'}`
  ]
  if (w.hot.some(h => h.src === 'sensor')) list.push('Sensor hotspots were added to the risk map where readings were elevated')
  list.push('No flame sensor or thermal camera data is available')
  return list
}

export default function EnvironmentMonitoring() {
  const { w, act, live } = useDashboard()
  const e = envOf(w), lvl = levelFromScore(e.score)
  const real = w.tel.source !== 'SIMULATED'
  const sc = real ? 'normal' : w.scenario, peak = SC[sc].peak
  const cells = []
  for (let y = 0; y < 24; y++) for (let x = 0; x < 32; x++) {
    const noise = Math.sin(x * 12.9 + y * 78.2 + (w.tick >> 3)) * 1.2
    const t = (real ? e.temp : 27) + noise + (sc === 'normal' ? 0 : (peak - 27) * Math.exp(-((x - 22) ** 2 + (y - 8) ** 2) / 12))
    cells.push(<rect key={`${x}-${y}`} x={x} y={y} width={1} height={1} fill={heat(t)} />)
  }
  return (
    <>
      <NoticeBox kind="warn">Prototype decision-support visualization only. Not a certified fire-alarm system.</NoticeBox>
      {live && <NoticeBox kind="info">Temperature, humidity and smoke are live {w.tel.source === 'LIVE_PI' ? 'Raspberry Pi' : 'serial'} readings from FireBird. The heatmap is a simulated placeholder because no thermal camera is connected.</NoticeBox>}
      {!live && real && <NoticeBox kind="warn">Raspberry Pi connection is inactive. Displaying the last real sensor readings without replacing them with simulated values.</NoticeBox>}
      <div className="flex flex-wrap items-center gap-2">
        {SCENARIO_LIST.map(([id, l]) => <Button key={id} active={w.scenario === id} disabled={real} title={real ? 'Scenarios are simulation-only' : ''} onClick={() => act(x => setScenario(x, id))}>{l}</Button>)}
        {real && <span className="text-xs text-slate-600">Scenario buttons are disabled while real readings are displayed.</span>}
      </div>
      <div className="grid gap-4 lg:grid-cols-3">
        <Card title="Current readings" right={<SourceBadge live={live} source={w.tel.source} />}>
          <div className="grid grid-cols-2 gap-2">
            <MetricTile label="Temperature" value={`${e.temp.toFixed(1)} Â°C`} t={e.temp >= TEMP_CRIT ? 'crit' : e.temp >= TEMP_WARN ? 'warn' : 'ok'} />
            <MetricTile label="Humidity" value={`${e.hum.toFixed(1)} %`} />
            <MetricTile label="Smoke value" value={e.smoke} t={e.smoke >= SMOKE_CRIT ? 'crit' : e.smoke >= SMOKE_WARN ? 'warn' : 'ok'} sub="raw sensor value" />
            <MetricTile label="Risk level" value={levelLabel[lvl]} t={levelTone(lvl)} />
          </div>
          {!live && w.scenario !== 'normal' && <p className="mt-2 text-xs text-slate-500">Scenario hotspot at {cellName(scenarioCell(w).r, scenarioCell(w).c)} on the map.</p>}
        </Card>
        <Card title="Fire-risk gauge" right={<SourceBadge live={live} source={w.tel.source} />}><Gauge score={e.score} /><p className={`mt-1 text-center text-sm font-semibold ${levelTone(lvl) === 'ok' ? 'text-ok' : levelTone(lvl) === 'warn' ? 'text-ember' : 'text-alarm'}`}>{levelLabel[lvl]} risk</p></Card>
        <Card title="Why this risk level?" right={<SourceBadge live={live} source={w.tel.source} />}><ul className="list-disc space-y-1 pl-5 text-sm text-slate-700">{evidence(w, real, live).map(x => <li key={x}>{x}</li>)}</ul></Card>
      </div>
      <div className="grid gap-4 md:grid-cols-3">
        <Card title="Temperature (Â°C)" right={<SourceBadge live={live} source={w.tel.source} />}><MetricLineChart data={w.hist} dataKey="temp" color="#d97706" unit="" refs={[{ y: TEMP_WARN, color: '#d97706' }, { y: TEMP_CRIT, color: '#dc2626' }]} /></Card>
        <Card title="Humidity (%)" right={<SourceBadge live={live} source={w.tel.source} />}><MetricLineChart data={w.hist} dataKey="hum" color="#0284c7" unit="" domain={[0, 100]} /></Card>
        <Card title="Smoke (raw value)" right={<SourceBadge live={live} source={w.tel.source} />}><MetricLineChart data={w.hist} dataKey="smoke" color="#64748b" unit="" refs={[{ y: SMOKE_WARN, color: '#d97706' }, { y: SMOKE_CRIT, color: '#dc2626' }]} /></Card>
      </div>
      <Card title="Thermal heatmap placeholder (32 x 24)" right={<Badge kind="sim">SIMULATED PLACEHOLDER</Badge>}>
        <svg viewBox="0 0 32 24" className="mx-auto w-full max-w-3xl rounded border border-line" role="img" aria-label="Simulated thermal heatmap placeholder">{cells}</svg>
        <div className="mx-auto mt-2 h-2 max-w-3xl rounded" style={{ background: `linear-gradient(90deg,${[20, 56, 92, 128, 164, 200].map(heat).join(',')})` }} />
        <div className="mx-auto flex max-w-3xl justify-between text-xs text-slate-500"><span>20 Â°C</span><span>200 Â°C+</span></div>
      </Card>
    </>
  )
}

