import { Bar, BarChart, CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'

const axis = { stroke: '#64748b', fontSize: 11 }
export function MetricLineChart({ data, dataKey, color, unit, refs = [], domain }: { data: object[]; dataKey: string; color: string; unit: string; refs?: { y: number; color: string }[]; domain?: [number, number] }) {
  return (
    <div className="h-48"><ResponsiveContainer><LineChart data={data}>
      <CartesianGrid stroke="#dbe3ee" /><XAxis dataKey="t" hide /><YAxis width={44} {...axis} domain={domain ?? ['auto', 'auto']} unit={unit} />
      <Tooltip contentStyle={{ background: '#fff', border: '1px solid #cbd5e1', fontSize: 12 }} />
      {refs.map(r => <ReferenceLine key={r.y} y={r.y} stroke={r.color} strokeDasharray="4 4" />)}
      <Line dataKey={dataKey} stroke={color} dot={false} strokeWidth={2} isAnimationActive={false} />
    </LineChart></ResponsiveContainer></div>
  )
}
export function EventFrequencyChart({ data }: { data: { module: string; count: number }[] }) {
  return (
    <div className="h-48"><ResponsiveContainer><BarChart data={data}>
      <CartesianGrid stroke="#dbe3ee" /><XAxis dataKey="module" {...axis} /><YAxis allowDecimals={false} width={30} {...axis} />
      <Tooltip contentStyle={{ background: '#fff', border: '1px solid #cbd5e1', fontSize: 12 }} /><Bar dataKey="count" fill="#0284c7" isAnimationActive={false} />
    </BarChart></ResponsiveContainer></div>
  )
}
