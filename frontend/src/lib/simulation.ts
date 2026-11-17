// Pure simulation engine. Nothing here talks to hardware or the network.
import type { Cell, DataSource, EventRec, FireBirdTelemetry, MapCell, Module, Movement, RouteRequest, RouteResponse, RouteState, Severity } from '../types'
import { blockedGrid, computeRisk, DIRS, emptyRoute, HEADINGS, planLocal, shortestInfo } from './mapUtils'
import { cellName, levelFromScore, parseCell, rawLine, SMOKE_CRIT, SMOKE_WARN, TEMP_CRIT, TEMP_WARN } from './format'

export type Scenario = 'normal' | 'warm' | 'hotspot' | 'fire'
export interface Hot { r: number; c: number; level: number; src?: 'user' | 'sensor'; temp?: number; smoke?: number }
export const SC: Record<Scenario, { T: number; H: number; S: number; peak: number; level: number }> = {
  normal: { T: 28, H: 45, S: 120, peak: 31, level: 0 }, warm: { T: 41, H: 42, S: 200, peak: 46, level: 30 },
  hotspot: { T: 50, H: 36, S: 380, peak: 78, level: 60 }, fire: { T: 78, H: 24, S: 820, peak: 340, level: 100 }
}

export interface World {
  tick: number; running: boolean; speed: number; mode: 'LIVE' | 'SIM'; startedAt: number
  size: number; obs: boolean[][]; persons: Cell[]; hot: Hot[]; start: Cell; goal: Cell | null; rover: Cell & { h: number }
  alpha: number; tool: string; sel: Cell | null
  route: RouteState; prev: Cell[] | null; simProgress: number
  following: boolean; paused: boolean; qi: number; awaiting: boolean; sentAt: number; obsUntil: number; slow: boolean; needsReplan: boolean; mv: Movement
  tel: FireBirdTelemetry; lastTelAt: number; prevObs: boolean; telLog: { t: number; src: string; raw: string }[]; lastLiveT: number
  events: EventRec[]; eid: number; outbox: string[]
  battery: number; scenario: Scenario; envLevel: number; maxTemp: number; hist: { t: number; temp: number; hum: number; smoke: number }[]
  cellUpdated: Record<string, number>
  personAction: 'ignore' | 'slow' | 'stop'; personCount: number; personLive: boolean; prevCount: number; nearFlag: boolean; stoppedByPerson: boolean
}

const grid = (n: number, v: boolean) => Array.from({ length: n }, () => Array<boolean>(n).fill(v))
const clamp = (v: number, a: number, b: number) => Math.max(a, Math.min(b, v))
export const MOVE_FROM_CMD: Record<string, Movement> = { 'MOVE:FORWARD': 'F', 'MOVE:BACKWARD': 'B', 'MOVE:LEFT': 'L', 'MOVE:RIGHT': 'R', 'MOVE:STOP': 'S' }

export function createWorld(size = 10): World {
  const obs = grid(size, false)
  if (size === 10) [[2, 2], [2, 3], [5, 5], [6, 5], [4, 7], [7, 2]].forEach(([r, c]) => (obs[r][c] = true))
  const now = Date.now()
  const w: World = {
    tick: 0, running: true, speed: 1, mode: 'SIM', startedAt: now, size, obs, persons: [], hot: [],
    start: { r: size - 1, c: 0 }, goal: null, rover: { r: size - 1, c: 0, h: 0 },
    alpha: 1.5, tool: 'select', sel: null, route: { ...emptyRoute }, prev: null, simProgress: 0,
    following: false, paused: false, qi: 0, awaiting: false, sentAt: 0, obsUntil: 0, slow: false, needsReplan: false, mv: 'S',
    tel: { leftIr: 100, centerIr: 100, rightIr: 100, sideIr: 100, temperatureTenths: 280, humidityTenths: 450, smokeValue: 120, obstacleDetected: false, movement: 'S', riskScore: 0, personCount: 0, timestamp: new Date(now).toISOString(), source: 'SIMULATED' },
    lastTelAt: 0, prevObs: false, telLog: [], lastLiveT: 0, events: [], eid: 0, outbox: [],
    battery: 100, scenario: 'normal', envLevel: 0, maxTemp: 28, hist: [], cellUpdated: {},
    personAction: 'stop', personCount: 0, personLive: false, prevCount: 0, nearFlag: false, stoppedByPerson: false
  }
  log(w, 'System', 'Dashboard started in SIMULATION MODE', 'Info')
  return w
}

export function resizeWorld(w: World, size: number) {
  const old = w.obs, inb = (c: Cell) => c.r < size && c.c < size
  w.size = size
  w.obs = grid(size, false).map((row, r) => row.map((_, c) => old[r]?.[c] ?? false))
  w.persons = w.persons.filter(inb); w.hot = w.hot.filter(inb)
  w.start = inb(w.start) ? w.start : { r: size - 1, c: 0 }
  w.goal = w.goal && inb(w.goal) ? w.goal : null
  w.rover = { ...w.start, h: 0 }; w.sel = null
  w.route = { ...emptyRoute, alpha: w.alpha }; w.prev = null; w.following = false; w.paused = false; w.simProgress = 0
  log(w, 'System', `Grid resized to ${size} x ${size}`, 'Info')
}

export function clearMap(w: World) {
  w.obs = grid(w.size, false); w.persons = []; w.hot = []; w.scenario = 'normal'
  w.route = { ...emptyRoute, alpha: w.alpha }; w.prev = null; w.following = false; w.paused = false; w.sel = null; w.simProgress = 0
  log(w, 'System', 'Map cleared', 'Info')
}

export function log(w: World, module: Module, event: string, severity: Severity = 'Info', cell?: Cell, action = 'None') {
  const source: DataSource = w.mode === 'LIVE' ? 'LIVE_SERIAL' : 'SIMULATED'
  w.events.unshift({ id: ++w.eid, t: Date.now(), severity, module, event, cell: cell ? cellName(cell.r, cell.c) : '-', action, status: 'Open', source })
  if (w.events.length > 300) w.events.length = 300
}

export const scenarioCell = (w: World): Cell => ({ r: Math.floor(w.size * 0.3), c: Math.floor(w.size * 0.6) })
export const hotList = (w: World): Hot[] => (w.scenario === 'normal' ? w.hot : [...w.hot, { ...scenarioCell(w), level: SC[w.scenario].level }])
export const riskOf = (w: World) => computeRisk(w.size, w.obs, hotList(w))
export const envOf = (w: World) => ({ temp: w.tel.temperatureTenths / 10, hum: w.tel.humidityTenths / 10, smoke: w.tel.smokeValue, score: w.tel.riskScore })

export function getCell(w: World, r: number, c: number): MapCell {
  const risk = riskOf(w)[r][c]
  const hot = hotList(w).find(h => h.r === r && h.c === c)
  const here = w.rover.r === r && w.rover.c === c
  let temperature: number | null = null, smoke: number | null = null
  if (w.mode === 'LIVE') {
    if (here) { temperature = w.tel.temperatureTenths / 10; smoke = w.tel.smokeValue } else if (hot?.src === 'sensor') { temperature = hot.temp ?? null; smoke = hot.smoke ?? null }
  } else { temperature = +(27 + risk * 0.5).toFixed(1); smoke = Math.round(120 + risk * 7) }
  return {
    row: r, column: c, coordinate: cellName(r, c), isObstacle: w.obs[r][c], isPerson: w.persons.some(p => p.r === r && p.c === c), isFire: !!hot && hot.level >= 60,
    temperature, smoke, riskScore: risk, riskLevel: w.obs[r][c] ? 'SAFE' : levelFromScore(risk), lastUpdated: new Date(w.cellUpdated[`${r},${c}`] ?? w.startedAt).toISOString()
  }
}

export function editCell(w: World, c: Cell) {
  const k = `${c.r},${c.c}`
  w.sel = c
  switch (w.tool) {
    case 'start': if (!w.following) { w.start = c; w.rover = { ...c, h: 0 } } break
    case 'goal': w.goal = c; break
    case 'obstacle': w.obs[c.r][c.c] = true; break
    case 'unobstacle': w.obs[c.r][c.c] = false; break
    case 'person': w.persons.push(c); break
    case 'hotspot': w.hot.push({ ...c, level: 75, src: 'user' }); break
    default: return
  }
  w.cellUpdated[k] = Date.now()
  if (w.tool !== 'person') { w.route = { ...emptyRoute, alpha: w.alpha }; w.following = false; w.paused = false }
  if (w.tool === 'start') w.simProgress = 0
}

export function setScenario(w: World, s: Scenario) {
  w.scenario = s
  const c = scenarioCell(w)
  const msg: Record<Scenario, [string, Severity, string]> = {
    normal: ['Scenario: normal area. Risk cleared (simulated)', 'Info', 'None'],
    warm: ['Warm equipment detected. Risk upgraded to yellow (simulated)', 'Warning', 'Monitor area'],
    hotspot: ['Smoke level increased. Risk upgraded to orange (simulated)', 'Warning', 'Avoid area, replan route'],
    fire: ['Confirmed fire: temperature and smoke critical, risk upgraded to red (simulated)', 'Critical', 'Keep away, replan around red cells']
  }
  log(w, 'Environment', msg[s][0], msg[s][1], c, msg[s][2])
}

export function buildRouteRequest(w: World): RouteRequest {
  const risk = riskOf(w)
  return {
    rows: w.size, columns: w.size, start: cellName(w.rover.r, w.rover.c), goal: w.goal ? cellName(w.goal.r, w.goal.c) : '', heading: HEADINGS[w.rover.h],
    obstacles: w.obs.flatMap((row, r) => row.map((o, c) => (o ? cellName(r, c) : ''))).filter(Boolean),
    persons: w.persons.map(p => cellName(p.r, p.c)),
    hazards: hotList(w).map(h => ({ coordinate: cellName(h.r, h.c), riskScore: h.level })), riskValues: risk, alpha: w.alpha
  }
}

export function planLocalFor(w: World): RouteState {
  if (!w.goal) return { ...emptyRoute, alpha: w.alpha, message: 'Select a destination to generate a route', status: 'Select a destination to generate a route' }
  return planLocal({ size: w.size, obs: w.obs, risk: riskOf(w), start: { r: w.rover.r, c: w.rover.c }, goal: w.goal, heading: w.rover.h, alpha: w.alpha })
}

/** Convert and validate a backend route response against its source grid. */
export function routeFromResponse(w: World, r: RouteResponse, grid?: { rows: number; columns: number }): RouteState {
  const dimensions = grid ?? { rows: w.size, columns: w.size }
  if (!r.found) return { ...emptyRoute, alpha: r.alpha, planner: 'backend', message: r.message, status: 'No safe route found', explanation: r.explanation ?? r.message }
  const path = r.cells.map(parseCell)
  if (path.length < 1 || path.some(p => !p || p.r < 0 || p.c < 0 || p.r >= dimensions.rows || p.c >= dimensions.columns)) {
    throw new Error('Backend returned route cells outside the source grid')
  }
  const cells = path as Cell[]
  const sh = !grid && w.goal
    ? shortestInfo(w.size, w.obs, riskOf(w), { r: w.rover.r, c: w.rover.c }, w.goal)
    : { risk: 0, length: 0 }
  return {
    found: true, path: cells, cmds: r.commands, cost: r.totalCost, risk: r.totalRisk, alpha: r.alpha, message: r.message,
    shortestRisk: r.shortestRisk ?? sh.risk, shortestLength: r.shortestCells ? r.shortestCells.length - 1 : sh.length,
    explanation: r.explanation ?? r.message, planner: 'backend', status: 'Route ready (backend planner)'
  }
}

export function applyRoute(w: World, rs: RouteState) {
  if (w.route.found) w.prev = w.route.path
  w.route = rs; w.qi = 0; w.simProgress = 0
  if (rs.found) {
    const names = rs.path.map(p => cellName(p.r, p.c))
    const shown = names.length > 5 ? [...names.slice(0, 3), '...', names[names.length - 1]] : names
    log(w, 'Path', `RAIR route calculated: ${shown.join(' → ')} (${names.length - 1} moves, alpha ${rs.alpha.toFixed(1)})`, 'Info', w.goal ?? undefined)
  } else log(w, 'Path', 'No safe route found', 'Critical', w.goal ?? undefined, 'Change goal or remove blocked cells')
}

export function startFollow(w: World) {
  if (!w.route.found) return
  w.following = true; w.paused = false; w.awaiting = false; w.qi = 0; w.stoppedByPerson = false
  if (w.mode === 'SIM') {
    w.simProgress = 0
    const routeStart = w.route.path[0] ?? w.rover
    w.rover = { ...routeStart, h: w.rover.h }
  }
  log(w, 'Path', w.mode === 'LIVE' ? 'Route following started (commands sent through backend)' : 'Route following started (simulated)', 'Info', w.goal ?? undefined)
}

function applyCmd(w: World, cmd: string): 'ok' | 'blocked' {
  const r = w.rover
  if (cmd === 'MOVE:LEFT') r.h = (r.h + 3) % 4
  else if (cmd === 'MOVE:RIGHT') r.h = (r.h + 1) % 4
  else if (cmd === 'MOVE:FORWARD') {
    const [dr, dc] = DIRS[r.h], nr = r.r + dr, nc = r.c + dc
    if (nr < 0 || nc < 0 || nr >= w.size || nc >= w.size || w.obs[nr][nc]) return 'blocked'
    r.r = nr; r.c = nc
  } else if (cmd === 'MOVE:BACKWARD') {
    const [dr, dc] = DIRS[r.h], nr = r.r - dr, nc = r.c - dc
    if (nr < 0 || nc < 0 || nr >= w.size || nc >= w.size || w.obs[nr][nc]) return 'blocked'
    r.r = nr; r.c = nc
  }
  return 'ok'
}
const aheadCell = (w: World): Cell => ({ r: w.rover.r + DIRS[w.rover.h][0], c: w.rover.c + DIRS[w.rover.h][1] })
const inGrid = (w: World, c: Cell) => c.r >= 0 && c.c >= 0 && c.r < w.size && c.c < w.size

function obstacleHit(w: World) {
  const c = aheadCell(w)
  if (inGrid(w, c)) { w.obs[c.r][c.c] = true; w.cellUpdated[`${c.r},${c.c}`] = Date.now() }
  w.obsUntil = w.tick + 8; w.outbox.push('MOVE:STOP'); w.awaiting = false
  w.paused = true; w.needsReplan = true
  log(w, 'Obstacle', 'Obstacle detected. Route paused. Replanning required.', 'Warning', c, 'Replanning route')
}

/** Advance the simulated rover along the planner's cell path, including turns. */
export function advanceSimulationRoute(w: World) {
  const path = w.route.path
  if (!w.route.found || path.length < 1) { w.following = false; return }
  if (path.length === 1) {
    w.rover = { ...path[0], h: w.rover.h }; w.following = false; w.paused = false
    log(w, 'Path', 'Simulation reached the destination', 'Info', w.rover)
    return
  }
  const total = path.length - 1
  const nextProgress = Math.min(total, w.simProgress + 0.12)
  const nextIndex = Math.min(Math.floor(nextProgress + 1e-9), total)
  const nextCell = path[nextIndex]
  if (w.obs[nextCell.r]?.[nextCell.c]) {
    w.following = false; w.paused = true; w.needsReplan = true
    log(w, 'Obstacle', 'A route cell became blocked. Simulation paused for replanning.', 'Warning', nextCell, 'Replanning route')
    return
  }
  w.simProgress = nextProgress
  const cellIndex = Math.min(Math.floor(nextProgress), total)
  const cell = path[cellIndex]
  w.rover.r = cell.r; w.rover.c = cell.c
  const segmentIndex = Math.min(Math.floor(nextProgress), total - 1)
  const a = path[segmentIndex], b = path[segmentIndex + 1]
  const dr = b.r - a.r, dc = b.c - a.c
  w.rover.h = dr < 0 ? 0 : dc > 0 ? 1 : dr > 0 ? 2 : 3
  w.mv = 'F'
  if (nextProgress >= total) {
    w.simProgress = total; w.rover = { r: path[total].r, c: path[total].c, h: w.rover.h }
    w.following = false; w.paused = false; w.mv = 'S'
    log(w, 'Path', 'Simulation reached the destination', 'Info', w.rover)
  }
}

/** Continuous map-space pose used only for simulated rendering and status. */
export function simulatedRoutePose(w: World) {
  const path = w.route.path
  if (w.mode !== 'SIM' || !w.route.found || path.length < 2) {
    return { x: w.rover.c + 0.5, y: w.rover.r + 0.5, heading: w.rover.h * Math.PI / 2 - Math.PI / 2 }
  }
  const total = path.length - 1, progress = Math.max(0, Math.min(total, w.simProgress))
  const index = Math.min(Math.floor(progress), total - 1), t = progress >= total ? 1 : progress - index
  const a = path[index], b = path[index + 1]
  let heading = Math.atan2(b.r - a.r, b.c - a.c)
  if (index > 0 && t < 0.2) {
    const before = path[index - 1], prior = Math.atan2(a.r - before.r, a.c - before.c)
    const delta = ((heading - prior + Math.PI * 3) % (Math.PI * 2)) - Math.PI
    const blend = Math.max(0, Math.min(1, t / 0.2))
    heading = prior + delta * blend
  }
  return { x: a.c + 0.5 + (b.c - a.c) * t, y: a.r + 0.5 + (b.r - a.r) * t,
    heading }
}

function liveStep(w: World) {
  if (w.tel.source !== 'LIVE_SERIAL' && w.tel.source !== 'LIVE_PI') return
  if (w.awaiting) {
    if (Date.now() - w.sentAt > 700 && w.tel.movement === 'S') {
      const cmd = w.route.cmds[w.qi]
      applyCmd(w, cmd); w.awaiting = false; w.qi++
      if (cmd === 'MOVE:STOP') { w.following = false; log(w, 'Path', 'Goal reached', 'Info', w.rover) }
    }
    return
  }
  if (Date.now() - w.sentAt < (w.slow ? 2500 : 0)) return
  if (w.tel.obstacleDetected) return obstacleHit(w)
  const cmd = w.route.cmds[w.qi]
  if (!cmd) { w.following = false; return }
  const a = aheadCell(w)
  if (cmd === 'MOVE:FORWARD' && (!inGrid(w, a) || w.obs[a.r][a.c])) return obstacleHit(w)
  w.outbox.push(cmd); w.awaiting = true; w.sentAt = Date.now()
}

function simTel(w: World): FireBirdTelemetry {
  const free = (turn: number) => {
    const [dr, dc] = DIRS[(w.rover.h + turn + 4) % 4]
    let n = 0, r = w.rover.r + dr, c = w.rover.c + dc
    while (r >= 0 && c >= 0 && r < w.size && c < w.size && !w.obs[r][c] && n < 5) { n++; r += dr; c += dc }
    return Math.min(150, n * 25 + 12 + (w.tick % 3))
  }
  const sc = SC[w.scenario], center = free(0)
  const T = sc.T + (w.tick % 5) * 0.1, S = sc.S + (w.tick % 7)
  const score = Math.round(Math.max(riskOf(w)[w.rover.r][w.rover.c], clamp(((T - 30) / 30) * 100, 0, 100), clamp(((S - 200) / 600) * 100, 0, 100)))
  return {
    leftIr: free(-1), centerIr: center, rightIr: free(1), sideIr: Math.min(150, free(1) + 5),
    temperatureTenths: Math.round(T * 10), humidityTenths: Math.round(sc.H * 10), smokeValue: S,
    obstacleDetected: center < 20 || w.tick < w.obsUntil, movement: w.following && !w.paused ? w.mv : 'S',
    riskScore: score, personCount: w.personCount, timestamp: new Date().toISOString(), source: 'SIMULATED'
  }
}

function updateEnv(w: World) {
  const { temp, hum, smoke, score } = envOf(w)
  w.maxTemp = Math.max(w.maxTemp, temp)
  if (w.tick % 5 === 0) { w.hist.push({ t: w.tick, temp, hum, smoke }); if (w.hist.length > 60) w.hist.shift() }
  if (w.mode !== 'LIVE') return
  if (score >= 30) {
    const h = w.hot.find(x => x.src === 'sensor' && x.r === w.rover.r && x.c === w.rover.c)
    if (h) { h.level = Math.max(h.level, score); h.temp = temp; h.smoke = smoke }
    else w.hot.push({ r: w.rover.r, c: w.rover.c, level: score, src: 'sensor', temp, smoke })
    w.cellUpdated[`${w.rover.r},${w.rover.c}`] = Date.now()
  }
  const lvl = temp >= TEMP_CRIT || smoke >= SMOKE_CRIT ? 2 : temp >= TEMP_WARN || smoke >= SMOKE_WARN ? 1 : 0
  if (lvl > w.envLevel) log(w, 'Environment', `Sensor reading ${lvl === 2 ? 'critical' : 'elevated'}: ${temp.toFixed(1)} °C, smoke ${smoke}`, lvl === 2 ? 'Critical' : 'Warning', w.rover, lvl === 2 ? 'Move away from area' : 'Monitor area')
  w.envLevel = lvl
}

export function tickSim(w: World) {
  w.tick++
  if (w.mode === 'SIM') {
    if (w.tick % 25 === 0) w.battery = Math.max(5, w.battery - 0.1)
    if (w.following && !w.paused && (!w.slow || w.tick % 6 === 0)) advanceSimulationRoute(w)
    if (!w.following) w.mv = 'S'
    w.tel = simTel(w)
    if (w.tick % 5 === 0) { w.telLog.unshift({ t: Date.now(), src: 'SIMULATED', raw: rawLine(w.tel) }); if (w.telLog.length > 80) w.telLog.length = 80 }
  }
  updateEnv(w)
  const obsNow = w.tel.obstacleDetected
  if (obsNow && !w.prevObs && !w.following) log(w, 'Obstacle', 'Obstacle detected ahead', 'Warning', aheadCell(w), 'Rover holds position')
  w.prevObs = obsNow

  const n = w.personCount
  if (n > w.prevCount) log(w, 'Person', `Person detected. Count updated to ${n}${w.personLive ? ' (camera)' : w.tel.source === 'LIVE_PI' ? ' (Raspberry Pi YOLO)' : ' (simulated)'}`, 'Info', undefined, w.personAction === 'ignore' ? 'None' : w.personAction === 'slow' ? 'Slow down' : 'Stop rover')
  w.prevCount = n
  w.slow = n > 0 && w.personAction === 'slow'
  if (n > 0 && w.personAction === 'stop' && w.following && !w.paused) {
    w.paused = true; w.stoppedByPerson = true; w.outbox.push('MOVE:STOP')
    log(w, 'Person', 'Person detected. Route following stopped.', 'Warning', w.rover, 'Resume when area is clear')
  }
  if (n === 0 && w.stoppedByPerson) { w.stoppedByPerson = false; log(w, 'Person', 'Area clear. Press Resume Route Following.', 'Info') }
  const risk = riskOf(w)
  const near = !w.personLive && w.persons.some(p => risk[p.r][p.c] >= 45)
  if (near && !w.nearFlag) log(w, 'Person', 'Person detected near high-risk zone.', 'Critical', undefined, 'Keep rover and people away')
  w.nearFlag = near
  if (w.mode === 'LIVE' && w.following && !w.paused) liveStep(w)
}

export function roverStatus(w: World) {
  if (w.scenario === 'fire' || w.envLevel === 2 || w.tel.riskScore >= 80) return 'ALERT'
  if (w.tel.obstacleDetected) return 'AVOIDING OBSTACLE'
  if (w.following) return w.paused ? 'STOPPED' : 'FOLLOWING PATH'
  return w.running || w.mode === 'LIVE' ? 'PATROLLING' : 'STOPPED'
}
export const blockedFor = (w: World) => blockedGrid(w.obs, riskOf(w))
export const SCENARIO_LIST: [Scenario, string][] = [['normal', 'Normal Area'], ['warm', 'Warm Equipment'], ['hotspot', 'Heat Hotspot'], ['fire', 'Confirmed Fire']]
