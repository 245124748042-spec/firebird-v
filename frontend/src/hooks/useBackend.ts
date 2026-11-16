import { useEffect, useRef, useState } from 'react'
import { api, WS_URL } from '../lib/api'
import type { BackendAlert, BackendStatus, FireBirdTelemetry, MapSnapshot, PersonStatus, WsMessage } from '../types'

export interface BackendState {
  online: boolean; checked: boolean; status: BackendStatus | null
  telemetry: FireBirdTelemetry | null; telemetryAt: number | null; raw: { t: number; line: string }[]
  map: MapSnapshot | null
  alerts: BackendAlert[]; person: PersonStatus | null; wsConnected: boolean; error: string | null
}
export const initialBackend: BackendState = { online: false, checked: false, status: null, telemetry: null, telemetryAt: null, raw: [], map: null, alerts: [], person: null, wsConnected: false, error: null }

/** LIVE only while the backend's last real telemetry is still fresh. */
export const isLive = (b: BackendState) =>
  b.online && b.status?.mode === 'LIVE' && (b.telemetry?.source === 'LIVE_SERIAL' || b.telemetry?.source === 'LIVE_PI') && b.telemetryAt !== null && Date.now() - b.telemetryAt < 4000

/** Polls the REST API and keeps a WebSocket open. Never throws: failures just mark the backend offline. */
export function useBackend(): BackendState {
  const [s, setS] = useState<BackendState>(initialBackend)
  const onlineRef = useRef(false), wsOk = useRef(false), lastTs = useRef('')

  useEffect(() => {
    let stop = false, ws: WebSocket | null = null, retry: number | undefined
    const patch = (p: Partial<BackendState>) => { if (!stop) setS(prev => ({ ...prev, ...p })) }
    const accept = (t: FireBirdTelemetry, raw?: string) => {
      if (t.source !== 'LIVE_SERIAL' && t.source !== 'LIVE_PI') return
      if (t.timestamp === lastTs.current) return
      lastTs.current = t.timestamp
      const now = Date.now()
      setS(prev => ({ ...prev, telemetry: t, telemetryAt: now, raw: raw ? [...prev.raw, { t: now, line: raw }].slice(-80) : prev.raw }))
    }

    const pollStatus = async () => {
      try { const st = await api.status(); onlineRef.current = true; patch({ online: true, checked: true, status: st, error: null }) }
      catch (e) { onlineRef.current = false; patch({ online: false, checked: true, status: null, person: null, wsConnected: false, error: (e as Error).message }) }
    }
    const pollTelemetry = async () => {
      if (!onlineRef.current || wsOk.current) return
      try {
        const r = await api.telemetry()
        if (r.latest) accept(r.latest)
        if (r.raw.length) patch({ raw: r.raw.slice(-80).map(x => ({ t: Date.parse(x.timestamp) || Date.now(), line: x.line })) })
      } catch { /* stay quiet, status poll reports offline */ }
    }
    const pollMap = async () => {
      if (!onlineRef.current || wsOk.current) return
      try { patch({ map: await api.map() }) } catch { /* status polling reports backend availability */ }
    }
    const pollPerson = async () => { if (onlineRef.current) { try { patch({ person: await api.personStatus() }) } catch { /* ignore */ } } }
    const pollAlerts = async () => { if (onlineRef.current) { try { patch({ alerts: await api.alerts() }) } catch { /* ignore */ } } }

    const connectWs = () => {
      if (stop) return
      try {
        ws = new WebSocket(WS_URL)
        ws.onopen = () => { wsOk.current = true; patch({ wsConnected: true }) }
        ws.onclose = () => { wsOk.current = false; patch({ wsConnected: false }); if (!stop) retry = window.setTimeout(connectWs, 4000) }
        ws.onerror = () => ws?.close()
        ws.onmessage = ev => {
          try {
            const m = JSON.parse(ev.data) as WsMessage
            if (m.type === 'telemetry') accept(m.data, m.raw)
            else if (m.type === 'map') patch({ map: m.data })
            else if (m.type === 'status') patch({ online: true, status: m.data })
            else if (m.type === 'person') patch({ person: m.data })
            else if (m.type === 'alert') setS(prev => ({ ...prev, alerts: [m.data, ...prev.alerts.filter(a => a.id !== m.data.id)].slice(0, 100) }))
          } catch { /* ignore malformed message */ }
        }
      } catch { retry = window.setTimeout(connectWs, 4000) }
    }

    pollStatus(); connectWs()
    const ids = [setInterval(pollStatus, 2000), setInterval(pollTelemetry, 1000), setInterval(pollMap, 1000), setInterval(pollPerson, 1000), setInterval(pollAlerts, 3000)]
    return () => { stop = true; ids.forEach(clearInterval); if (retry) clearTimeout(retry); ws?.close() }
  }, [])
  return s
}
