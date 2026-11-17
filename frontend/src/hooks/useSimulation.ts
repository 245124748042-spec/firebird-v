import { MutableRefObject, useEffect, useRef, useState } from 'react'
import { api } from '../lib/api'
import { advanceSimulationRoute, createWorld, log, tickSim, World } from '../lib/simulation'
import { isLive, BackendState } from './useBackend'

/** Owns the world object and runs the 200 ms loop while the dashboard is open. */
export function useSimulation(active: boolean, backendRef: MutableRefObject<BackendState>) {
  const ref = useRef<World>(createWorld())
  const [, setN] = useState(0)
  const bump = () => setN(n => n + 1)
  const [speed, setSpeedS] = useState(1)

  useEffect(() => {
    if (!active) return
    const id = setInterval(() => {
      const w = ref.current, b = backendRef.current
      const m = isLive(b) ? 'LIVE' : 'SIM'
      const piMode = !!b.status?.raspberryPi?.enabled
      const retainPiReadings = piMode && b.telemetry?.source === 'LIVE_PI' && !isLive(b)
      if (m !== w.mode) {
        w.mode = m; w.following = false; w.awaiting = false
        if (!retainPiReadings) { w.scenario = 'normal'; w.envLevel = 0; w.hist = []; w.maxTemp = 0 }
        if (m === 'LIVE') log(w, 'System', `LIVE MODE: FireBird telemetry received through ${b.telemetry?.source === 'LIVE_PI' ? 'Raspberry Pi Wi-Fi' : b.status?.serial.port ?? 'serial port'}. Simulated sensor values stopped.`, 'Info')
        else log(w, 'System', piMode ? 'Raspberry Pi disconnected. SIMULATION MODE is active; the last real readings are retained.' : 'Serial telemetry lost or robot disconnected. Back in SIMULATION MODE.', 'Warning', undefined, piMode ? 'Check Raspberry Pi Wi-Fi forwarding' : 'Check cable, COM port and backend')
      }
      if (m === 'LIVE' && b.telemetry && b.telemetryAt !== w.lastTelAt) {
        w.tel = b.telemetry; w.lastTelAt = b.telemetryAt!
        for (const l of b.raw) if (l.t > w.lastLiveT) { w.telLog.unshift({ t: l.t, src: b.telemetry.source, raw: l.line }); w.lastLiveT = l.t }
        if (w.telLog.length > 80) w.telLog.length = 80
      }
      if (retainPiReadings) {
        w.personCount = b.person?.count ?? b.status?.raspberryPi?.personCount ?? w.tel.personCount
        if (w.mode === 'SIM' && w.running && w.following && !w.paused) advanceSimulationRoute(w)
        bump()
        return
      }
      if (m === 'SIM' && !w.running) { bump(); return }
      const p = b.person, cam = !!p?.cameraActive
      w.personLive = cam
      w.personCount = piMode ? (p?.count ?? b.status?.raspberryPi?.personCount ?? w.tel.personCount) : cam ? (p?.count ?? 0) : m === 'LIVE' ? w.tel.personCount : w.persons.length
      tickSim(w)
      while (w.outbox.length) {
        const c = w.outbox.shift()!
        if (m === 'LIVE') {
          w.telLog.unshift({ t: Date.now(), src: 'PC to FIREBIRD', raw: c })
          api.command(c).catch(e => log(w, 'System', `Command ${c} rejected: ${e.message}`, 'Warning'))
        }
      }
      bump()
    }, 200 / speed)
    return () => clearInterval(id)
  }, [active, speed, backendRef])

  return {
    w: ref.current, speed,
    act: (f: (w: World) => void) => { f(ref.current); bump() },
    reset: () => { const o = ref.current; const n = createWorld(o.size); n.mode = o.mode; n.personAction = o.personAction; n.alpha = o.alpha; ref.current = n; bump() },
    setSpeed: (n: number) => { ref.current.speed = n; setSpeedS(n) }
  }
}
