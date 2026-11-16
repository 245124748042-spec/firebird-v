import { MutableRefObject, useRef, useState } from 'react'
import { api } from '../lib/api'
import { applyRoute, buildRouteRequest, log, planLocalFor, routeFromResponse, startFollow, World } from '../lib/simulation'
import { cellName } from '../lib/format'
import type { BackendState } from './useBackend'
import type { RouteState } from '../types'
import type { Cell } from '../types'

/** Asks the backend for a route (POST /api/map/route). Falls back to the local planner when the backend is offline or fails. */
export function useRoutePlanner(w: World, act: (f: (w: World) => void) => void, backendRef: MutableRefObject<BackendState>) {
  const [planning, setPlanning] = useState(false)
  const destinationRequestId = useRef(0)

  const calculate = async (): Promise<boolean> => {
    const currentBackend = backendRef.current
    const liveMode = currentBackend.status?.mode === 'LIVE'
    const liveGoal = currentBackend.map?.goal ?? currentBackend.status?.goal
    if (liveMode ? !liveGoal : !w.goal) {
      act(x => { x.route = { ...x.route, found: false, path: [], cmds: [], planner: 'none', message: 'Select a destination to generate a route', status: 'Select a destination to generate a route' } })
      return false
    }
    setPlanning(true)
    let rs: RouteState | null = null
    let note = ''
    const b = currentBackend
    if (b.online && b.status?.planner !== 'unavailable') {
      if (b.status?.mode === 'LIVE' && !b.map) note = 'Waiting for the live occupancy and risk map.'
      else try {
        const request = b.status?.mode === 'LIVE'
          ? { rows: b.map!.rows, columns: b.map!.columns, start: cellName(b.map!.rover.row, b.map!.rover.column), goal: liveGoal!, heading: b.map!.rover.heading, alpha: w.alpha }
          : buildRouteRequest(w)
        const response = await api.route(request)
        rs = routeFromResponse(w, response, b.status?.mode === 'LIVE' && b.map
          ? { rows: b.map.rows, columns: b.map.columns }
          : undefined)
      } catch (e) { note = `Backend planner failed (${(e as Error).message}).` }
    }
    // In live mode the route must come from the backend's real risk/occupancy map.
    // A local simulation fallback could draw a path through stale or invented cells.
    const result = rs ?? (b.status?.mode === 'LIVE'
      ? { ...w.route, found: false, path: [], cmds: [], planner: 'none' as const, message: note || 'Backend planner unavailable', status: 'Planner unavailable' }
      : planLocalFor(w))
    act(x => { if (note) log(x, 'System', note, 'Warning'); applyRoute(x, result) })
    setPlanning(false)
    return result.found
  }

  // In LIVE mode the backend map is authoritative. Selecting a cell submits it
  // directly to the existing A* endpoint, which stores the goal and returns the
  // route on the same occupancy/risk grid.
  const setDestination = async (cell: Cell) => {
    const requestId = ++destinationRequestId.current
    const b = backendRef.current
    if (b.status?.mode !== 'LIVE' || !b.map) {
      act(x => { x.goal = cell; x.route = { ...x.route, found: false, path: [], cmds: [], planner: 'none', status: 'Destination selected; calculate a route' } })
      return
    }
    act(x => { x.goal = cell; x.route = { ...x.route, found: false, path: [], cmds: [], planner: 'none', status: 'Calculating route' } })
    setPlanning(true)
    try {
      const response = await api.route({
        rows: b.map.rows, columns: b.map.columns,
        start: cellName(b.map.rover.row, b.map.rover.column),
        goal: cellName(cell.r, cell.c), heading: b.map.rover.heading, alpha: w.alpha
      })
      if (requestId !== destinationRequestId.current) return
      const result = routeFromResponse({ ...w, goal: cell }, response, { rows: b.map.rows, columns: b.map.columns })
      act(x => applyRoute(x, result))
      if (result.found) {
        try { await api.routeControl('start') }
        catch (e) {
          const reason = (e as Error).message
          act(x => { x.route = { ...x.route, status: `Route ready; automatic navigation not started: ${reason}` } })
        }
      }
    } catch (e) {
      if (requestId === destinationRequestId.current) {
        act(x => { x.route = { ...x.route, found: false, path: [], cmds: [], planner: 'none', status: `Route failed: ${(e as Error).message}` } })
      }
    } finally { if (requestId === destinationRequestId.current) setPlanning(false) }
  }

  const sendRoute = async () => {
    const ok = w.route.found || (await calculate())
    if (ok) act(x => startFollow(x))
  }
  return { calculate, sendRoute, setDestination, planning }
}
