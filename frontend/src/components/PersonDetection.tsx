import { Camera, CameraOff } from 'lucide-react'
import { useDashboard } from '../hooks/useDashboard'
import { personStreamUrl } from '../lib/api'
import Button from './Button'
import Card from './Card'
import MetricTile from './MetricTile'
import { Badge, NoticeBox } from './Badge'

export default function PersonDetection() {
  const { w, backend, act, personCfg, setPersonCfg, startCamera, stopCamera } = useDashboard()
  const piMode = !!backend.status?.raspberryPi?.enabled
  const p = backend.person, cam = !!p?.cameraActive
  const n = piMode ? (p?.count ?? backend.status?.raspberryPi?.personCount ?? null) : w.personCount
  const missing = !!p && p.modelLoaded === false && /not found|missing/i.test(p.modelError ?? 'missing')
  const l1 = n == null ? 'YOLO: WAITING' : n === 0 ? 'PERSONS: 0' : `${n} PERSON${n === 1 ? '' : 'S'}`, l2 = n == null ? 'COUNT NOT RECEIVED' : n === 0 ? 'AREA CLEAR' : 'DETECTED'
  return (
    <>
      <NoticeBox kind="info">This counts people visible in the current camera frame. It does not identify individuals and does not track entry/exit.</NoticeBox>
      {piMode && <NoticeBox kind="info">Person counts come from YOLO on the Raspberry Pi. The Pi camera preview is not sent to this dashboard.</NoticeBox>}
      {piMode && n == null && <NoticeBox kind="warn">Waiting for a Raspberry Pi person count. The laptop cannot confirm whether the Pi webcam or ONNX process is running.</NoticeBox>}
      {backend.checked && !backend.online && <NoticeBox kind="warn">Backend service offline. The camera needs the Python service. The preview below is a simulated placeholder.</NoticeBox>}
      {p && (missing || p.modelError) && <NoticeBox kind="warn">{missing ? 'Model not found. Place trained .pt file in backend/models/.' : p.modelError}</NoticeBox>}
      {p?.error && <NoticeBox kind="warn">{p.error}</NoticeBox>}
      {w.nearFlag && <NoticeBox kind="crit">Person detected near high-risk zone.</NoticeBox>}
      <div className="grid gap-4 lg:grid-cols-3">
        <div className="lg:col-span-2">
          <Card title="Camera view" right={cam ? <Badge kind="live">LIVE CAMERA (YOLO)</Badge> : piMode ? <Badge kind="info">PI IMAGE NOT STREAMED</Badge> : <Badge kind="sim">SIMULATED</Badge>}>
            {cam ? (
              <div className="relative">
                <img src={personStreamUrl()} alt="Laptop camera stream" className="w-full rounded border border-line bg-black" />
                {p!.detections.map((d, i) => d.box && (
                  <div key={i} className="absolute border-2 border-scan" style={{ left: `${d.box[0] * 100}%`, top: `${d.box[1] * 100}%`, width: `${d.box[2] * 100}%`, height: `${d.box[3] * 100}%` }}>
                    <span className="absolute -top-5 left-0 whitespace-nowrap bg-scan px-1 font-mono text-[11px] text-white">{d.label || `Person ${i + 1}`} — {(d.confidence * 100).toFixed(0)}%</span>
                  </div>))}
              </div>
            ) : (
              <svg viewBox="0 0 320 180" className="w-full rounded border border-line bg-slate-100" role="img" aria-label={piMode ? 'Raspberry Pi camera preview unavailable' : 'Simulated camera placeholder'}>
                <text x={160} y={20} textAnchor="middle" fontSize={10} fill="#475569">{piMode ? 'Pi camera frames are not forwarded to this dashboard.' : 'SIMULATED placeholder. Start the camera for real detection.'}</text>
                {!piMode && w.persons.map((_, i) => <g key={i}><rect x={30 + i * 70} y={50} width={50} height={100} fill="none" stroke="#0284c7" strokeWidth={2} /><text x={30 + i * 70} y={44} fontSize={9} fill="#0284c7">Person {i + 1} (sim)</text></g>)}
              </svg>)}
          </Card>
        </div>
        <div className="space-y-4">
          <Card title="Detection">
            <div className="grid grid-cols-2 gap-2">
              <MetricTile label="Visible people" value={n ?? 'Waiting'} t={n == null ? 'gray' : n ? 'warn' : 'ok'} sub={piMode ? 'Raspberry Pi YOLO count' : cam ? 'Stable over 3 frames' : 'Simulated'} />
              <MetricTile label="Confidence" value={cam && p!.detections.length ? p!.detections.map(d => (d.confidence * 100).toFixed(0) + '%').join(' ') : '-'} />
              <MetricTile label="Camera FPS" value={cam ? p!.fps.toFixed(1) : '-'} />
              <MetricTile label="Inference" value={cam ? `${p!.latencyMs.toFixed(0)} ms` : '-'} sub="Measured" />
              <MetricTile label="Model" value={piMode ? 'Pi status unavailable' : p ? (p.modelLoaded ? 'loaded' : 'not loaded') : 'unknown'} t={piMode ? 'gray' : p?.modelLoaded ? 'ok' : 'warn'} />
              <MetricTile label="Serial message" value={p?.lastSerialMessage ?? '-'} sub="sent to FireBird" />
            </div>
            <p className="mt-2 break-all font-mono text-xs text-slate-500">{p?.modelPath ?? 'backend/models/ (path reported by backend)'}</p>
          </Card>
          <Card title="FireBird LCD preview"><pre className="rounded bg-slate-900 p-3 font-mono text-sm text-ok" aria-label="LCD preview">{`${l1.padEnd(16)}\n${l2.padEnd(16)}`}</pre></Card>
          <Card title="Controls">
            <div className="flex flex-wrap gap-2">
              <Button kind="primary" disabled={!backend.online || cam || piMode} onClick={startCamera}><Camera size={14} />{piMode ? 'Pi Camera Active' : 'Start Camera'}</Button>
              <Button disabled={!backend.online || !cam || piMode} onClick={stopCamera}><CameraOff size={14} />Stop Camera</Button>
            </div>
            <label className="mt-3 block text-sm">Confidence threshold: <span className="font-mono">{personCfg.threshold.toFixed(2)}</span>
              <input type="range" min={0.3} max={0.9} step={0.05} value={personCfg.threshold} onChange={e => setPersonCfg({ threshold: +e.target.value })} className="w-full" /></label>
            <label className="mt-2 flex items-center gap-2 text-sm"><input type="checkbox" checked={personCfg.send} onChange={e => setPersonCfg({ send: e.target.checked })} />Send person count to FireBird</label>
            <label className="mt-2 block text-sm">Person safety action
              <select value={w.personAction} onChange={e => act(x => (x.personAction = e.target.value as typeof x.personAction))} className="mt-1 block w-full rounded-md border border-line bg-base px-2 py-1.5">
                <option value="ignore">Ignore</option><option value="slow">Slow down (wait 2.5 s between commands)</option><option value="stop">Stop rover</option></select></label>
          </Card>
        </div>
      </div>
    </>
  )
}
