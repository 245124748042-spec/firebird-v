"""Grid map and risk map.

Each hazard is a *source* (obstacle, person, thermal, smoke). Source intensity spreads to neighbouring cells:

    neighbor_risk = source_risk * exp(-k * distance)

Components (0..1) per cell: obstacle, person, thermal, smoke. Two numbers are derived from them:
  * risk_score (0..100): the strongest component. Used for colours, levels and blocking.
  * risk01 (0..1): weighted sum W_OBS*obs + W_PERSON*person + W_THERMAL*thermal + W_SMOKE*smoke + W_HEALTH*health.
    Used by the RAIR planner as risk(n).
"""
from __future__ import annotations

import logging
import math
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import numpy as np

from config import Settings
from schemas import MapCell, RiskLevel, utcnow

logger = logging.getLogger("firebird.map")

HEADINGS = ("N", "E", "S", "W")
DELTAS = ((-1, 0), (0, 1), (1, 0), (0, -1))  # row, column change for N, E, S, W
CRITICAL_SCORE = 75.0


def risk_level(score: float) -> RiskLevel:
    """SAFE 0-24, CAUTION 25-49, WARNING 50-74, CRITICAL 75-100."""
    return "SAFE" if score < 25 else "CAUTION" if score < 50 else "WARNING" if score < 75 else "CRITICAL"


def coordinate(row: int, col: int) -> str:
    return f"{chr(65 + row)}{col + 1}"


def parse_coordinate(text: str) -> tuple[int, int]:
    """'C4' -> (2, 3). Raises ValueError for anything else."""
    t = text.strip().upper()
    if len(t) < 2 or not t[0].isalpha() or not t[1:].isdigit():
        raise ValueError(f"Invalid coordinate '{text}'. Use a letter and a number, e.g. C4.")
    return ord(t[0]) - 65, int(t[1:]) - 1


@dataclass
class Source:
    kind: str  # thermal | smoke | person
    row: int
    col: int
    intensity: float  # 0..1
    fire: bool = False
    origin: str = "user"  # user | sensor | camera
    decay_rate: float = 0.0  # per second; 0 = permanent until removed


@dataclass
class RoverPose:
    row: int
    col: int
    heading: int = 0  # index into HEADINGS


@dataclass
class Overlay:
    """Temporary extra hazards used for one planning request. Never stored."""
    obstacles: set = field(default_factory=set)
    persons: list = field(default_factory=list)
    hazards: list = field(default_factory=list)  # (row, col, intensity, fire)
    floor: Optional[np.ndarray] = None  # 0..100 risk values supplied by the dashboard


@dataclass
class CostGrid:
    rows: int
    cols: int
    blocked: np.ndarray
    risk01: np.ndarray
    risk_score: np.ndarray


class RiskMap:
    """Thread-safe grid map. All public methods take the internal lock."""

    def __init__(self, settings: Settings, rows: Optional[int] = None, cols: Optional[int] = None) -> None:
        self.s = settings
        self._lock = threading.RLock()
        self.rows = rows or settings.map_rows
        self.cols = cols or settings.map_columns
        self.obstacles: set[tuple[int, int]] = set()
        self.sensor_obstacles: set[tuple[int, int]] = set()
        self.latched_sensor_obstacles: set[tuple[int, int]] = set()
        self.sources: list[Source] = []
        self.measured: dict[tuple[int, int], tuple[float, float]] = {}
        self.reported_risk: dict[tuple[int, int], tuple[float, float]] = {}
        self.touched: dict[tuple[int, int], datetime] = {}
        self.created = utcnow()
        self.pose = RoverPose(self.rows - 1, 0, 0)
        self.odometry_path: list[dict[str, float]] = []
        self.odometry_heading_rad: Optional[float] = None
        self.goal: Optional[tuple[int, int]] = None
        self.health_risk = 0.0
        self.version = 0
        self._cache: Optional[tuple[int, dict]] = None

    # ------------------------------------------------------------ helpers
    def _bump(self, *cells: tuple[int, int]) -> None:
        now = utcnow()
        for c in cells:
            self.touched[c] = now
        self.version += 1

    def in_bounds(self, r: int, c: int) -> bool:
        return 0 <= r < self.rows and 0 <= c < self.cols

    def _check(self, r: int, c: int) -> None:
        if not self.in_bounds(r, c):
            raise ValueError(f"Cell ({r}, {c}) is outside the {self.rows} x {self.cols} map.")

    # ------------------------------------------------------------ structure
    def resize(self, rows: int, cols: int) -> None:
        if not (5 <= rows <= 20 and 5 <= cols <= 20):
            raise ValueError("Map size must be between 5 x 5 and 20 x 20.")
        with self._lock:
            self.rows, self.cols = rows, cols
            inb = lambda r, c: self.in_bounds(r, c)  # noqa: E731
            self.obstacles = {(r, c) for r, c in self.obstacles if inb(r, c)}
            self.sensor_obstacles = {(r, c) for r, c in self.sensor_obstacles if inb(r, c)}
            self.latched_sensor_obstacles = {(r, c) for r, c in self.latched_sensor_obstacles if inb(r, c)}
            self.sources = [s for s in self.sources if inb(s.row, s.col)]
            self.measured = {k: v for k, v in self.measured.items() if inb(*k)}
            self.reported_risk = {k: v for k, v in self.reported_risk.items() if inb(*k)}
            if not inb(self.pose.row, self.pose.col):
                self.pose = RoverPose(rows - 1, 0, 0)
            if self.goal and not inb(*self.goal):
                self.goal = None
            self._bump()
            logger.info("Map resized to %d x %d", rows, cols)

    def clear(self) -> None:
        with self._lock:
            self.obstacles.clear(); self.sensor_obstacles.clear(); self.latched_sensor_obstacles.clear(); self.sources.clear(); self.measured.clear(); self.reported_risk.clear(); self.touched.clear()
            self._bump()

    def set_goal(self, row: int, col: int) -> None:
        with self._lock:
            self._check(row, col)
            self.goal = (row, col)
            self._bump((row, col))

    def set_health_risk(self, value: float) -> None:
        with self._lock:
            self.health_risk = max(0.0, min(1.0, value))

    # ------------------------------------------------------------ editing
    def add_obstacle(self, r: int, c: int) -> None:
        with self._lock:
            self._check(r, c)
            self.obstacles.add((r, c)); self._bump((r, c))

    def set_sensor_obstacle(self, r: int, c: int, detected: bool) -> None:
        """Track a forward IR obstacle until telemetry confirms the path is clear."""
        with self._lock:
            if not self.in_bounds(r, c):
                return
            cell = (r, c)
            if detected:
                previous = set(self.sensor_obstacles)
                self.sensor_obstacles.clear()
                self.sensor_obstacles.add(cell)
                self._bump(*(previous | {cell}))
            elif self.sensor_obstacles:
                previous = set(self.sensor_obstacles)
                self.sensor_obstacles.clear()
                self._bump(*previous)

    def clear_sensor_obstacles(self) -> None:
        with self._lock:
            if self.sensor_obstacles or self.latched_sensor_obstacles:
                previous = set(self.sensor_obstacles) | set(self.latched_sensor_obstacles)
                self.sensor_obstacles.clear(); self.latched_sensor_obstacles.clear()
                self._bump(*previous)

    def latch_sensor_obstacle(self, r: int, c: int) -> None:
        with self._lock:
            if self.in_bounds(r, c):
                self.latched_sensor_obstacles.add((r, c))
                self._bump((r, c))

    def apply_action(self, r: int, c: int, action: str) -> str:
        """Apply one of the dashboard cell actions. Returns a short description."""
        with self._lock:
            self._check(r, c)
            name = coordinate(r, c)
            if action == "ADD_OBSTACLE":
                self.obstacles.add((r, c))
            elif action == "REMOVE_OBSTACLE":
                self.obstacles.discard((r, c))
            elif action == "ADD_PERSON":
                if not any(s.kind == "person" and s.origin == "user" and (s.row, s.col) == (r, c) for s in self.sources):
                    self.sources.append(Source("person", r, c, 1.0, origin="user"))
            elif action == "REMOVE_PERSON":
                self.sources = [s for s in self.sources if not (s.kind == "person" and s.origin == "user" and (s.row, s.col) == (r, c))]
            elif action == "ADD_HOTSPOT":
                self.sources.append(Source("thermal", r, c, 0.85, origin="user"))
                self.sources.append(Source("smoke", r, c, 0.4, origin="user"))
            elif action == "REMOVE_HOTSPOT":
                self.sources = [s for s in self.sources if not (s.kind in ("thermal", "smoke") and s.origin == "user" and (s.row, s.col) == (r, c))]
            elif action == "CLEAR_CELL":
                self.obstacles.discard((r, c))
                self.sources = [s for s in self.sources if not ((s.row, s.col) == (r, c) and s.origin == "user")]
            else:
                raise ValueError(f"Unknown action '{action}'.")
            self._bump((r, c))
            return f"{action} at {name}"

    def user_person_count(self) -> int:
        with self._lock:
            return sum(1 for s in self.sources if s.kind == "person" and s.origin == "user" and s.intensity >= 0.3)

    def persons_near_hazard(self, threshold: float = 50.0) -> list[str]:
        """Coordinates of person marks that sit in a thermal or smoke zone with score >= threshold."""
        with self._lock:
            d = self._components()
            out = []
            for s in self.sources:
                if s.kind == "person" and s.intensity >= 0.3 and self.in_bounds(s.row, s.col):
                    if 100.0 * max(float(d["th"][s.row, s.col]), float(d["sm"][s.row, s.col])) >= threshold:
                        out.append(coordinate(s.row, s.col))
            return out

    def set_camera_presence(self, present: bool, cell: Optional[tuple[int, int]]) -> None:
        """Camera counts are not localized. When a person is seen, the cell ahead of the rover is marked
        (an approximation). When the count returns to 0 the mark decays quickly."""
        with self._lock:
            cams = [s for s in self.sources if s.kind == "person" and s.origin == "camera"]
            if present and cell and self.in_bounds(*cell):
                for s in cams:
                    s.decay_rate = 0.0; s.intensity = 1.0
                if not cams:
                    self.sources.append(Source("person", cell[0], cell[1], 1.0, origin="camera"))
                self._bump(cell)
            elif not present:
                for s in cams:
                    s.decay_rate = 0.5
                if cams:
                    self.version += 1

    def mark_sensor(self, r: int, c: int, temp_c: float, smoke_raw: float,
                    reported_risk: Optional[float] = None) -> None:
        """Update the risk map from REAL FireBird sensor readings at the rover's cell."""
        with self._lock:
            if not self.in_bounds(r, c):
                return
            th = max(0.0, min(1.0, (temp_c - 30.0) / 30.0))
            span = max(1, self.s.smoke_high - self.s.smoke_baseline)
            sm = max(0.0, min(1.0, (smoke_raw - self.s.smoke_baseline) / span))
            self.measured[(r, c)] = (temp_c, smoke_raw)
            if reported_risk is not None:
                self.reported_risk[(r, c)] = (max(0.0, min(100.0, reported_risk)), time.monotonic())
            for kind, val in (("thermal", th), ("smoke", sm)):
                if val < 0.1:
                    continue
                src = next((s for s in self.sources if s.origin == "sensor" and s.kind == kind and (s.row, s.col) == (r, c)), None)
                if src:
                    src.intensity = max(src.intensity, val)
                    src.fire = kind == "thermal" and src.intensity >= 0.95
                else:
                    self.sources.append(Source(kind, r, c, val, fire=(kind == "thermal" and val >= 0.95), origin="sensor", decay_rate=self.s.risk_decay_per_s))
            self._bump((r, c))

    def decay(self, dt: float) -> None:
        """Fade sensor and camera sources when nothing refreshes them."""
        with self._lock:
            changed = False
            keep: list[Source] = []
            for s in self.sources:
                if s.decay_rate > 0:
                    s.intensity *= math.exp(-s.decay_rate * dt)
                    if s.intensity < 0.9:
                        s.fire = False
                    changed = True
                    if s.intensity < 0.03:
                        continue
                keep.append(s)
            self.sources = keep
            if self.reported_risk and self.s.risk_decay_per_s > 0:
                factor = math.exp(-self.s.risk_decay_per_s * dt)
                for cell, (score, touched_at) in list(self.reported_risk.items()):
                    score *= factor
                    if score < 3.0:
                        del self.reported_risk[cell]
                    else:
                        self.reported_risk[cell] = (score, touched_at)
                    changed = True
            if changed:
                self.version += 1

    # ------------------------------------------------------------ rover pose
    def cell_ahead(self) -> tuple[int, int]:
        with self._lock:
            d = DELTAS[self.pose.heading]
            return self.pose.row + d[0], self.pose.col + d[1]

    def set_pose(self, row: int, col: int, heading: Optional[int] = None) -> None:
        with self._lock:
            self._check(row, col)
            self.pose = RoverPose(row, col, self.pose.heading if heading is None else heading % 4)
            self._bump((row, col))

    def set_odometry_pose(self, x_m: float, y_m: float, heading_rad: float, cell_size_m: float,
                          origin_row: int, origin_col: int) -> None:
        """Project the physical odometry frame into this map and retain its actual track."""
        with self._lock:
            world_x = origin_col + 0.5 + x_m / cell_size_m
            world_y = origin_row + 0.5 - y_m / cell_size_m
            col = max(0, min(self.cols - 1, math.floor(world_x)))
            row = max(0, min(self.rows - 1, math.floor(world_y)))
            # Odometry heading is radians counter-clockwise from east; map heading starts north.
            heading = round(((math.pi / 2 - heading_rad) % (2 * math.pi)) / (math.pi / 2)) % 4
            old = (self.pose.row, self.pose.col)
            self.pose = RoverPose(row, col, heading)
            self.odometry_heading_rad = heading_rad % (2 * math.pi)
            self.odometry_path.append({"x": world_x, "y": world_y})
            self.odometry_path = self.odometry_path[-2000:]
            self._bump(old, (row, col))

    def apply_pose_command(self, cmd: str) -> bool:
        """Dead-reckon one completed command. Returns False if a FORWARD was blocked (map edge or obstacle)."""
        with self._lock:
            if cmd == "MOVE:LEFT":
                self.pose.heading = (self.pose.heading + 3) % 4
            elif cmd == "MOVE:RIGHT":
                self.pose.heading = (self.pose.heading + 1) % 4
            elif cmd == "MOVE:FORWARD":
                r, c = self.cell_ahead()
                if not self.in_bounds(r, c) or (r, c) in self.obstacles:
                    return False
                self.pose.row, self.pose.col = r, c
            elif cmd == "MOVE:BACKWARD":
                dr, dc = DELTAS[(self.pose.heading + 2) % 4]
                r, c = self.pose.row + dr, self.pose.col + dc
                if not self.in_bounds(r, c) or (r, c) in self.obstacles:
                    return False
                self.pose.row, self.pose.col = r, c
            self.version += 1
            return True

    # ------------------------------------------------------------ computation
    def _compute(self, overlay: Optional[Overlay] = None) -> dict:
        s = self.s
        rr, cc = np.mgrid[0:self.rows, 0:self.cols]
        obs, per, th, sm = (np.zeros((self.rows, self.cols)) for _ in range(4))

        def spread(arr: np.ndarray, r: int, c: int, v: float, k: float) -> None:
            np.maximum(arr, v * np.exp(-k * np.hypot(rr - r, cc - c)), out=arr)

        obstacles = set(self.obstacles) | set(self.sensor_obstacles) | set(self.latched_sensor_obstacles) | (overlay.obstacles if overlay else set())
        for r, c in obstacles:
            spread(obs, r, c, 1.0, s.risk_spread_k_obstacle)
        srcs = [(x.kind, x.row, x.col, x.intensity, x.fire) for x in self.sources]
        if overlay:
            srcs += [("person", r, c, 1.0, False) for r, c in overlay.persons]
            srcs += [("thermal", r, c, i, f) for r, c, i, f in overlay.hazards]
        fire_cells: set[tuple[int, int]] = set()
        person_cells: set[tuple[int, int]] = set()
        for kind, r, c, inten, fire in srcs:
            if not self.in_bounds(r, c):
                continue
            if kind == "thermal":
                spread(th, r, c, inten, s.risk_spread_k_thermal)
                if fire:
                    fire_cells.add((r, c))
            elif kind == "smoke":
                spread(sm, r, c, inten, s.risk_spread_k_smoke)
            elif kind == "person":
                spread(per, r, c, inten, s.risk_spread_k_person)
                if inten >= 0.3:
                    person_cells.add((r, c))
        if overlay is not None and overlay.floor is not None:
            th = np.maximum(th, overlay.floor / 100.0)
        score = 100.0 * np.max([obs, per, th, sm], axis=0)
        reported = np.zeros((self.rows, self.cols), dtype=float)
        for (r, c), (value, _) in self.reported_risk.items():
            if self.in_bounds(r, c):
                reported[r, c] = value / 100.0
        score = np.maximum(score, reported * 100.0)
        blocked = score >= CRITICAL_SCORE
        for r, c in obstacles | fire_cells | person_cells:
            if self.in_bounds(r, c):
                blocked[r, c] = True
        risk01 = np.clip(s.w_obs * obs + s.w_person * per + s.w_thermal * th + s.w_smoke * sm + s.w_health * self.health_risk, 0.0, 1.0)
        # max() combines the firmware's aggregate score without adding the same
        # temperature/smoke hazard twice to the route cost.
        risk01 = np.maximum(risk01, reported)
        return {"obs": obs, "per": per, "th": th, "sm": sm, "score": score, "blocked": blocked, "risk01": risk01,
                "fire": fire_cells, "persons": person_cells, "obstacles": obstacles}

    def _components(self) -> dict:
        with self._lock:
            if self._cache is None or self._cache[0] != self.version:
                self._cache = (self.version, self._compute())
            return self._cache[1]

    def cost_grid(self, overlay: Optional[Overlay] = None) -> CostGrid:
        with self._lock:
            d = self._compute(overlay) if overlay else self._components()
            return CostGrid(self.rows, self.cols, d["blocked"].copy(), d["risk01"].copy(), d["score"].copy())

    def sample(self, r: int, c: int) -> dict:
        """Thermal / smoke / obstacle components (0..1) at one cell. Used by the simulation."""
        with self._lock:
            d = self._components()
            return {"thermal": float(d["th"][r, c]), "smoke": float(d["sm"][r, c]), "score": float(d["score"][r, c])}

    def is_blocked(self, r: int, c: int) -> bool:
        with self._lock:
            return (not self.in_bounds(r, c)) or bool(self._components()["blocked"][r, c])

    def has_physical_obstacle(self, r: int, c: int) -> bool:
        with self._lock:
            return (not self.in_bounds(r, c)) or (r, c) in self.obstacles

    # ------------------------------------------------------------ output
    def get_cell(self, r: int, c: int, live: bool) -> MapCell:
        with self._lock:
            self._check(r, c)
            d = self._components()
            score = float(d["score"][r, c])
            if live:
                temp, smoke = self.measured.get((r, c), (None, None))
            else:  # simulation: estimated from the modelled hazards
                temp = round(27.0 + 50.0 * float(d["th"][r, c]), 1)
                smoke = round(self.s.smoke_baseline + float(d["sm"][r, c]) * (self.s.smoke_high - self.s.smoke_baseline), 0)
            return MapCell(
                row=r, column=c, coordinate=coordinate(r, c), is_obstacle=(r, c) in self.obstacles or (r, c) in self.sensor_obstacles or (r, c) in self.latched_sensor_obstacles,
                is_sensor_obstacle=(r, c) in self.sensor_obstacles or (r, c) in self.latched_sensor_obstacles,
                is_person=(r, c) in d["persons"], is_fire=((r, c) in d["fire"]) or float(d["th"][r, c]) >= 0.7 and any(
                    x.kind == "thermal" and (x.row, x.col) == (r, c) for x in self.sources),
                temperature=temp, smoke=smoke, risk_score=round(score, 1), risk_level=risk_level(score),
                last_updated=self.touched.get((r, c), self.created))

    def cells(self, live: bool) -> list[MapCell]:
        with self._lock:
            return [self.get_cell(r, c, live) for r in range(self.rows) for c in range(self.cols)]

    def snapshot_meta(self) -> dict:
        with self._lock:
            p = self.pose
            return {"rows": self.rows, "columns": self.cols, "version": self.version,
                    "rover": {"row": p.row, "column": p.col, "coordinate": coordinate(p.row, p.col), "heading": HEADINGS[p.heading]},
                    "goal": coordinate(*self.goal) if self.goal else None,
                    "odometry_path": list(self.odometry_path), "odometry_available": bool(self.odometry_path),
                    "odometry_heading_rad": self.odometry_heading_rad}
