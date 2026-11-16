import { ReactNode, useEffect, useRef, useState } from 'react'
import { Maximize2, Minimize2 } from 'lucide-react'

/** A native browser fullscreen surface shared by the map and camera panels. */
export default function FullscreenPanel({ children, className = '' }: { children: ReactNode; className?: string }) {
  const ref = useRef<HTMLDivElement>(null)
  const [active, setActive] = useState(false)
  const [error, setError] = useState('')
  useEffect(() => {
    const update = () => setActive(document.fullscreenElement === ref.current)
    document.addEventListener('fullscreenchange', update)
    return () => document.removeEventListener('fullscreenchange', update)
  }, [])
  const toggle = async () => {
    setError('')
    try {
      if (document.fullscreenElement === ref.current) await document.exitFullscreen()
      else { if (document.fullscreenElement) await document.exitFullscreen(); await ref.current?.requestFullscreen() }
    } catch { setError('Fullscreen is unavailable in this browser.') }
  }
  return <div ref={ref} className={`relative ${active ? 'fullscreen-panel h-screen w-screen overflow-auto bg-slate-950 p-4' : ''} ${className}`}>
    <button type="button" onClick={toggle} aria-label={active ? 'Exit full screen' : 'Enter full screen'} title={active ? 'Exit full screen (Esc)' : 'Full screen'} className="absolute right-3 top-3 z-10 rounded-md border border-slate-600 bg-slate-900/90 p-2 text-slate-100 hover:bg-slate-700">
      {active ? <Minimize2 size={16} /> : <Maximize2 size={16} />}
    </button>
    {children}{error && <span role="status" className="absolute bottom-3 left-3 rounded bg-slate-900 px-2 py-1 text-xs text-amber-300">{error}</span>}
  </div>
}
