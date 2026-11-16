import { useState } from 'react'
import { Camera } from 'lucide-react'
import { useDashboard } from '../hooks/useDashboard'
import { personStreamUrl } from '../lib/api'
import FullscreenPanel from './FullscreenPanel'
import Card from './Card'
import { Badge } from './Badge'

export default function CameraPanel() {
  const { backend, w } = useDashboard()
  const piMode = !!backend.status?.raspberryPi?.enabled
  const cameraActive = !!backend.person?.cameraActive && !piMode
  const count = backend.person?.count ?? backend.status?.raspberryPi?.personCount ?? (w.tel.source === 'SIMULATED' ? w.personCount : null)
  const [streamFailed, setStreamFailed] = useState(false)
  const available = cameraActive && !streamFailed
  return <FullscreenPanel><Card title="Live webcam" icon={<Camera size={16} />} right={<Badge kind={available ? 'live' : piMode ? 'warn' : 'gray'}>{available ? 'STREAM CONNECTED' : piMode ? 'PI PREVIEW UNAVAILABLE' : 'STREAM UNAVAILABLE'}</Badge>} className="h-full">
    <div className="grid gap-4 xl:grid-cols-[minmax(0,2fr)_minmax(220px,1fr)]">
      <div className="flex min-h-[220px] items-center justify-center overflow-hidden rounded-md border border-slate-700 bg-black">
        {available ? <img key={personStreamUrl()} src={personStreamUrl()} alt="Backend person detection camera stream" className="max-h-[60vh] w-full object-contain" onError={() => setStreamFailed(true)} /> : <div className="max-w-lg p-8 text-center">
          <Camera size={30} className="mx-auto text-slate-500" />
          <p className="mt-3 text-sm font-semibold text-slate-200">{piMode ? 'Raspberry Pi camera preview is not available' : backend.checked && !backend.online ? 'Backend is disconnected' : streamFailed ? 'Camera stream could not be loaded' : 'Camera stream is not active'}</p>
          <p className="mt-1 text-xs leading-relaxed text-slate-400">{piMode ? 'The current backend reports Pi person counts, but does not forward camera frames to the dashboard.' : 'Start the existing backend camera from Person Detection to display its stream here. No device camera is opened by this page.'}</p>
        </div>}
      </div>
      <div className="flex flex-col justify-center rounded-md border border-slate-700 bg-slate-900/60 p-5">
        <div className="text-xs uppercase tracking-wider text-slate-400">Person detections</div>
        <div className="mt-2 font-mono text-4xl font-semibold text-slate-100">{count == null ? '—' : count}</div>
        <div className="mt-3 text-sm text-slate-400">{piMode ? 'Count from Raspberry Pi YOLO' : cameraActive ? `YOLO active · ${backend.person?.fps.toFixed(1) ?? '—'} FPS` : 'Waiting for camera data'}</div>
      </div>
    </div>
  </Card></FullscreenPanel>
}
