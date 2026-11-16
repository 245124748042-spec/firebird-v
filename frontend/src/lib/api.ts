import type { BackendAlert, BackendStatus, MapSnapshot, PersonStatus, RouteRequest, RouteResponse, TelemetryResponse } from '../types'

export const API_BASE_URL: string = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'
export const WS_URL = API_BASE_URL.replace(/^http/, 'ws') + '/ws/dashboard'

async function request<T>(path: string, init?: RequestInit, timeoutMs = 2500): Promise<T> {
  const ctl = new AbortController()
  const timer = setTimeout(() => ctl.abort(), timeoutMs)
  try {
    const res = await fetch(API_BASE_URL + path, { ...init, signal: ctl.signal, headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) } })
    if (!res.ok) {
      let detail = ''
      try { detail = (await res.json()).detail ?? '' } catch { /* ignore */ }
      throw new Error(detail || `HTTP ${res.status}`)
    }
    return (await res.json()) as T
  } finally { clearTimeout(timer) }
}
const post = <T,>(path: string, body?: unknown, timeout?: number) => request<T>(path, { method: 'POST', body: JSON.stringify(body ?? {}) }, timeout)

export const api = {
  health: () => request<{ status: string }>('/api/health'),
  status: () => request<BackendStatus>('/api/status'),
  telemetry: () => request<TelemetryResponse>('/api/telemetry'),
  map: () => request<MapSnapshot>('/api/map'),
  command: (command: string) => post<{ sent: string }>('/api/command', { command }),
  route: (req: RouteRequest) => post<RouteResponse>('/api/map/route', req, 6000),
  routeControl: (action: 'start' | 'pause' | 'resume' | 'stop') => post<{ success: boolean; executor: Record<string, unknown> }>(`/api/route/${action}`),
  emergencyStop: () => post<{ success: boolean; executor: Record<string, unknown>; message: string }>('/api/navigation/emergency-stop'),
  resetEmergencyStop: () => post<{ success: boolean; emergencyStopLatched: boolean }>('/api/navigation/reset-emergency-stop'),
  cell: (cell: unknown) => post<unknown>('/api/map/cell', cell),
  alerts: () => request<BackendAlert[]>('/api/alerts'),
  ackAlerts: (ids: number[] | 'all') => post<unknown>('/api/alerts/acknowledge', { ids }),
  personStatus: () => request<PersonStatus>('/api/person/status'),
  personStart: (cfg: { confidenceThreshold: number; sendToFireBird: boolean }) => post<PersonStatus>('/api/person/start', cfg, 8000),
  personStop: () => post<PersonStatus>('/api/person/stop'),
  /** Not in the base endpoint list: assumed extras for the Connect / Disconnect Robot buttons. */
  connect: () => post<unknown>('/api/serial/connect', {}, 7000),
  disconnect: () => post<unknown>('/api/serial/disconnect'),
  autonomous: () => post<{ success: boolean; message: string }>('/api/serial/autonomous')
}
export const personStreamUrl = () => `${API_BASE_URL}/api/person/stream?ts=${Date.now() >> 12}`
