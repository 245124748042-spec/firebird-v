import { createContext, ReactNode, useContext, useEffect, useRef, useState } from 'react'
import { api } from '../lib/api'
import { editCell, log, World } from '../lib/simulation'
import type { BackendAlert, Cell, EventRec } from '../types'
import { BackendState, isLive, useBackend } from './useBackend'
import { useSimulation } from './useSimulation'
import { useRoutePlanner } from './useRoutePlanner'

interface PersonCfg { threshold: number; send: boolean }
export interface Dash {
  w: World; live: boolean; backend: BackendState; speed: number; setSpeed: (n: number) => void
  act: (f: (w: World) => void) => void; reset: () => void
  calculate: () => Promise<boolean>; sendRoute: () => Promise<void>; setDestination: (cell: Cell) => Promise<void>; planning: boolean
  startNavigation: () => Promise<void>; pauseNavigation: () => Promise<void>; resumeNavigation: () => Promise<void>; stopNavigation: () => Promise<void>
  emergencyStop: () => Promise<void>
  resetEmergencyStop: () => Promise<void>
  click: (c: Cell) => void
  connectRobot: () => Promise<void>; disconnectRobot: () => Promise<void>; connectingRobot: boolean
  personCfg: PersonCfg; startCamera: () => Promise<void>; stopCamera: () => Promise<void>; setPersonCfg: (p: Partial<PersonCfg>) => void
  allEvents: EventRec[]; ackAll: () => void; clearNoncritical: () => void
}
const Ctx = createContext<Dash>(null as unknown as Dash)
export const useDashboard = () => useContext(Ctx)

const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1).toLowerCase()
const toEvent = (a: BackendAlert): EventRec => ({ id: 1_000_000 + a.id, backendId: a.id, t: Date.parse(a.timestamp) || Date.now(), severity: cap(a.severity) as EventRec['severity'], module: cap(a.module) as EventRec['module'], event: a.event, cell: a.gridLocation, action: a.recommendedAction, status: a.acknowledged || a.status === 'Acknowledged' ? 'Acknowledged' : 'Open', source: 'LIVE_SERIAL' })

export function DashboardProvider({ active, children }: { active: boolean; children: ReactNode }) {
  const backend = useBackend()
  const backendRef = useRef(backend)
  backendRef.current = backend
  const sim = useSimulation(active, backendRef)
  const { w, act } = sim
  const planner = useRoutePlanner(w, act, backendRef)
  const [personCfg, setCfg] = useState<PersonCfg>({ threshold: 0.6, send: true })
  const [connectingRobot, setConnectingRobot] = useState(false)

  // Obstacle or person stop: recalculate automatically, then resume.
  useEffect(() => {
    if (!w.needsReplan) return
    w.needsReplan = false
    planner.calculate().then(ok => act(x => {
      if (ok) { x.following = true; x.paused = false; x.qi = 0; log(x, 'Path', 'Route resumed after obstacle cleared', 'Info', x.goal ?? undefined) } else x.following = false
    }))
  })

  const note = (msg: string) => act(x => log(x, 'System', msg, 'Warning'))
  const navAction = async (action: 'start' | 'pause' | 'resume' | 'stop') => {
    try { await api.routeControl(action) } catch (e) { note(`Navigation ${action} failed: ${(e as Error).message}`) }
  }
  const emergencyStop = async () => {
    try { await api.emergencyStop() } catch (e) { note(`Emergency STOP failed: ${(e as Error).message}. Verify the rover locally.`) }
  }
  const resetEmergencyStop = async () => {
    try { await api.resetEmergencyStop() } catch (e) { note(`Emergency STOP reset refused: ${(e as Error).message}`) }
  }
  const startCamera = async () => { try { await api.personStart({ confidenceThreshold: personCfg.threshold, sendToFireBird: personCfg.send }) } catch (e) { note(`Camera start failed: ${(e as Error).message}`) } }
  const stopCamera = async () => { try { await api.personStop() } catch (e) { note(`Camera stop failed: ${(e as Error).message}`) } }

  const dash: Dash = {
    ...sim, ...planner, w, live: isLive(backend), backend, personCfg, connectingRobot,
    startNavigation: () => navAction('start'), pauseNavigation: () => navAction('pause'),
    resumeNavigation: () => navAction('resume'), stopNavigation: () => navAction('stop'),
    emergencyStop,
    resetEmergencyStop,
    click: c => {
      act(x => editCell(x, c))
      // Live map edits must use real backend-side observations; never post locally
      // simulated cells over the real sensor map.
    },
    connectRobot: async () => { setConnectingRobot(true); try { await api.connect() } catch (e) { note(`Connect failed: ${(e as Error).message}`) } finally { setConnectingRobot(false) } },
    disconnectRobot: async () => { try { await api.disconnect() } catch (e) { note(`Disconnect failed: ${(e as Error).message}`) } },
    startCamera, stopCamera,
    setPersonCfg: p => {
      const next = { ...personCfg, ...p }
      setCfg(next)
      if (backend.person?.cameraActive) api.personStart({ confidenceThreshold: next.threshold, sendToFireBird: next.send }).catch(() => { /* ignore */ })
    },
    allEvents: [...w.events, ...backend.alerts.map(toEvent)].sort((a, b) => b.t - a.t),
    ackAll: () => {
      act(x => x.events.forEach(e => (e.status = 'Acknowledged')))
      if (backend.online) api.ackAlerts('all').catch(() => { /* ignore */ })
    },
    clearNoncritical: () => act(x => (x.events = x.events.filter(e => e.severity === 'Critical')))
  }
  return <Ctx.Provider value={dash}>{children}</Ctx.Provider>
}
