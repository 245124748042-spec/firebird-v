"""A* and the RAIR-inspired Risk-Attitude-Aware A*.

Standard A*:      f(n) = g(n) + h(n), h = Manhattan distance, 4-direction moves.
RAIR-inspired A*: f(n) = g(n) + h(n) + alpha * risk(n)

Implementation note: the risk term is added to the cost of *every cell the route enters*, so g(n) already
holds the accumulated risk cost and f(n) = g(n) + h(n) stays consistent. One step costs

    1 + alpha * RISK_COST_SCALE * risk(n)        (risk(n) in 0..1)

alpha 0.5 = risk-seeking, 1.5 = risk-neutral, 3.0 = risk-averse, 5.0 = highly risk-averse.
This is RAIR-inspired, not the published RAIR algorithm.
"""
from __future__ import annotations

import heapq
import itertools
from typing import Optional

from risk_map import DELTAS, HEADINGS, CostGrid, coordinate
from schemas import PlannedRoute

Cell = tuple[int, int]


def astar(grid: CostGrid, start: Cell, goal: Cell, alpha: Optional[float], scale: float) -> tuple[bool, list[Cell], float]:
    """4-direction A*. `alpha=None` gives plain shortest-path A*. Blocked cells are never expanded.
    The start cell is always allowed (the rover is already standing there)."""
    def ok(r: int, c: int) -> bool:
        return 0 <= r < grid.rows and 0 <= c < grid.cols
    if not ok(*start) or not ok(*goal) or grid.blocked[goal]:
        return False, [], 0.0
    h = lambda r, c: abs(r - goal[0]) + abs(c - goal[1])  # noqa: E731  Manhattan heuristic
    tie = itertools.count()
    g = {start: 0.0}
    came: dict[Cell, Cell] = {}
    heap = [(float(h(*start)), next(tie), start)]
    closed: set[Cell] = set()
    while heap:
        _, _, cur = heapq.heappop(heap)
        if cur in closed:
            continue
        if cur == goal:
            path = [cur]
            while path[-1] in came:
                path.append(came[path[-1]])
            return True, path[::-1], g[cur]
        closed.add(cur)
        for dr, dc in DELTAS:
            nr, nc = cur[0] + dr, cur[1] + dc
            if not ok(nr, nc) or grid.blocked[nr, nc] or (nr, nc) in closed:
                continue
            step = 1.0 + (0.0 if alpha is None else alpha * scale * float(grid.risk01[nr, nc]))
            ng = g[cur] + step
            if ng < g.get((nr, nc), float("inf")):
                g[(nr, nc)] = ng
                came[(nr, nc)] = cur
                heapq.heappush(heap, (ng + h(nr, nc), next(tie), (nr, nc)))
    return False, [], 0.0


def to_commands(path: list[Cell], heading: int) -> list[str]:
    """One FORWARD moves one cell, LEFT/RIGHT turn 90 degrees, STOP at the end."""
    cmds: list[str] = []
    h = heading
    for a, b in zip(path, path[1:]):
        d = DELTAS.index((b[0] - a[0], b[1] - a[1]))
        diff = (d - h) % 4
        if diff == 1:
            cmds.append("MOVE:RIGHT")
        elif diff == 2:
            cmds += ["MOVE:RIGHT", "MOVE:RIGHT"]
        elif diff == 3:
            cmds.append("MOVE:LEFT")
        cmds.append("MOVE:FORWARD")
        h = d
    cmds.append("MOVE:STOP")
    return cmds


def route_risk(grid: CostGrid, path: list[Cell]) -> float:
    """Sum of risk scores (0..100) of the cells the route enters."""
    return round(float(sum(grid.risk_score[r, c] for r, c in path[1:])), 1)


def attitude(alpha: float) -> str:
    return "risk-seeking" if alpha < 1.0 else "risk-neutral" if alpha < 2.25 else "risk-averse" if alpha < 4.0 else "highly risk-averse"


def plan_route(grid: CostGrid, start: Cell, goal: Cell, heading: int, alpha: float, risk_aware: bool, scale: float) -> PlannedRoute:
    """Plan a route and compare it with the plain shortest A* route."""
    found_s, short, _ = astar(grid, start, goal, None, scale)
    if not found_s:
        return PlannedRoute(found=False, alpha=alpha, message="No safe route found.", explanation="Every path to the goal is blocked by obstacles, people, fire or critical-risk cells.")
    short_risk = route_risk(grid, short)
    if risk_aware:
        found, path, cost = astar(grid, start, goal, alpha, scale)
    else:
        found, path, cost = True, short, float(len(short) - 1)
    if not found:
        return PlannedRoute(found=False, alpha=alpha, message="No safe route found.")
    risk = route_risk(grid, path)
    extra = (len(path) - 1) - (len(short) - 1)
    if not risk_aware:
        why = "Standard A* (risk-aware mode off): the shortest route is used."
    elif extra <= 0 and risk >= short_risk:
        why = f"Alpha {alpha:.1f} ({attitude(alpha)}): the shortest route is also the lowest-risk option available."
    elif extra <= 0:
        why = f"Alpha {alpha:.1f} ({attitude(alpha)}): same length as the shortest route but total risk {risk} instead of {short_risk}."
    else:
        why = (f"Alpha {alpha:.1f} ({attitude(alpha)}): {extra} extra move(s) chosen to reduce route risk to {risk} "
               f"(the shortest route has risk {short_risk}).") if risk < short_risk else (
            f"Alpha {alpha:.1f} ({attitude(alpha)}): route takes {extra} extra move(s); risk {risk} versus {short_risk} on the shortest route.")
    return PlannedRoute(
        found=True, cells=[coordinate(r, c) for r, c in path], commands=to_commands(path, heading), total_cost=round(cost, 2),
        total_risk=risk, alpha=alpha, message="Route found.", shortest_cells=[coordinate(r, c) for r, c in short],
        shortest_length=len(short) - 1, shortest_risk=short_risk, extra_moves=extra, explanation=why,
        planner="rair-astar" if risk_aware else "astar")


def heading_index(letter: Optional[str], default: int = 0) -> int:
    return HEADINGS.index(letter) if letter in HEADINGS else default
