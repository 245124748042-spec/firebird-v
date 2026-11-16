import type { Cell, RouteState } from '../types'

export const DIRS: [number, number][] = [[-1, 0], [0, 1], [1, 0], [0, -1]] // N, E, S, W
export const HEADINGS = ['N', 'E', 'S', 'W'] as const
export const BLOCK_RISK = 70 // critical cells are never entered
export const emptyRoute: RouteState = { found: false, path: [], cmds: [], cost: 0, risk: 0, alpha: 1.5, message: 'No route calculated', shortestRisk: 0, shortestLength: 0, explanation: '', planner: 'none', status: 'No route calculated' }

export function computeRisk(size: number, obs: boolean[][], hots: { r: number; c: number; level: number }[]): number[][] {
  return Array.from({ length: size }, (_, r) => Array.from({ length: size }, (_, c) => {
    if (obs[r]?.[c]) return 0
    return Math.round(hots.reduce((m, h) => Math.max(m, h.level * Math.exp(-((r - h.r) ** 2 + (c - h.c) ** 2) / 3)), 0))
  }))
}
export const blockedGrid = (obs: boolean[][], risk: number[][]) => obs.map((row, r) => row.map((o, c) => o || risk[r][c] >= BLOCK_RISK))
export const pathRisk = (risk: number[][], path: Cell[]) => path.slice(1).reduce((s, p) => s + risk[p.r][p.c], 0)

/** 4-direction A*. Step cost = 1 + penalty(risk). alpha = null means plain shortest path (no penalty). */
export function astar(size: number, blocked: boolean[][], risk: number[][], s: Cell, g: Cell, alpha: number | null) {
  const none = { found: false, path: [] as Cell[], cost: 0 }
  if (blocked[s.r]?.[s.c] || blocked[g.r]?.[g.c]) return none
  const k = (r: number, c: number) => r * size + c
  const gs = Array<number>(size * size).fill(Infinity), came = Array<number>(size * size).fill(-1), closed = new Set<number>()
  const h = (r: number, c: number) => Math.abs(r - g.r) + Math.abs(c - g.c)
  const open = [k(s.r, s.c)]
  gs[k(s.r, s.c)] = 0
  while (open.length) {
    let bi = 0
    for (let i = 1; i < open.length; i++) {
      const a = open[i], b = open[bi]
      if (gs[a] + h(Math.floor(a / size), a % size) < gs[b] + h(Math.floor(b / size), b % size)) bi = i
    }
    const cur = open.splice(bi, 1)[0]
    const r = Math.floor(cur / size), c = cur % size
    if (r === g.r && c === g.c) {
      const path: Cell[] = []
      for (let n = cur; n !== -1; n = came[n]) path.unshift({ r: Math.floor(n / size), c: n % size })
      return { found: true, path, cost: gs[cur] }
    }
    closed.add(cur)
    for (const [dr, dc] of DIRS) {
      const nr = r + dr, nc = c + dc
      if (nr < 0 || nc < 0 || nr >= size || nc >= size || blocked[nr][nc] || closed.has(k(nr, nc))) continue
      const ng = gs[cur] + 1 + (alpha == null ? 0 : 0.1 * alpha * risk[nr][nc])
      if (ng < gs[k(nr, nc)]) { gs[k(nr, nc)] = ng; came[k(nr, nc)] = cur; if (!open.includes(k(nr, nc))) open.push(k(nr, nc)) }
    }
  }
  return none
}

/** One FORWARD = one cell, LEFT/RIGHT = 90 degree turn, final STOP. */
export function toCommands(path: Cell[], heading: number): string[] {
  const cmds: string[] = []
  let h = heading
  for (let i = 0; i < path.length - 1; i++) {
    const d = DIRS.findIndex(([dr, dc]) => path[i].r + dr === path[i + 1].r && path[i].c + dc === path[i + 1].c)
    const diff = (d - h + 4) % 4
    if (diff === 1) cmds.push('MOVE:RIGHT')
    else if (diff === 2) cmds.push('MOVE:RIGHT', 'MOVE:RIGHT')
    else if (diff === 3) cmds.push('MOVE:LEFT')
    cmds.push('MOVE:FORWARD')
    h = d
  }
  cmds.push('MOVE:STOP')
  return cmds
}

export function shortestInfo(size: number, obs: boolean[][], risk: number[][], s: Cell, g: Cell) {
  const sh = astar(size, blockedGrid(obs, risk), risk, s, g, null)
  return { length: sh.found ? sh.path.length - 1 : 0, risk: sh.found ? pathRisk(risk, sh.path) : 0 }
}

/** RAIR-inspired local planner: risk-weighted A* with a risk-attitude parameter alpha (high = risk-averse). */
export function planLocal(p: { size: number; obs: boolean[][]; risk: number[][]; start: Cell; goal: Cell; heading: number; alpha: number }): RouteState {
  const { size, obs, risk, start, goal, heading, alpha } = p
  const res = astar(size, blockedGrid(obs, risk), risk, start, goal, alpha)
  if (!res.found) return { ...emptyRoute, alpha, planner: 'local', message: 'No safe route found', status: 'No safe route found', explanation: 'Every path to the goal is blocked by obstacles or critical-risk cells.' }
  const sh = shortestInfo(size, obs, risk, start, goal)
  const len = res.path.length - 1, rr = pathRisk(risk, res.path), extra = len - sh.length
  const att = alpha < 1 ? 'risk-seeking' : alpha < 2.25 ? 'risk-neutral' : alpha < 4 ? 'risk-averse' : 'highly risk-averse'
  const explanation = extra <= 0 && rr >= sh.risk
    ? `Alpha ${alpha.toFixed(1)} (${att}): the shortest route is also the safest available. Route risk ${rr}.`
    : `Alpha ${alpha.toFixed(1)} (${att}): ${len} moves with risk ${rr}. The shortest route has ${sh.length} moves with risk ${sh.risk}, so this route takes ${extra} extra move(s) to lower exposure.`
  return { found: true, path: res.path, cmds: toCommands(res.path, heading), cost: +res.cost.toFixed(2), risk: rr, alpha, message: 'Route found', shortestRisk: sh.risk, shortestLength: sh.length, explanation, planner: 'local', status: 'Route ready (local simulation planner)' }
}
