"""Simulated FireBird used when no robot is connected. Every sample carries source = SIMULATED."""
from __future__ import annotations

import logging
import random
import threading
from typing import Callable, Optional

from config import Settings
from risk_map import DELTAS, RiskMap
from schemas import Telemetry, utcnow

logger = logging.getLogger("firebird.sim")

IR_CLEAR = 600  # raw IR value reported when the way is clear (simulated scale)
IR_OBSTACLE_BELOW = 200  # front IR below this => OBS:1 (simulated threshold)
MOVE_TICKS = {"MOVE:FORWARD": 5, "MOVE:BACKWARD": 5, "MOVE:LEFT": 3, "MOVE:RIGHT": 3}  # ticks per step at 1x
LETTER = {"MOVE:FORWARD": "F", "MOVE:BACKWARD": "B", "MOVE:LEFT": "L", "MOVE:RIGHT": "R"}


class SimulationService:
    def __init__(self, settings: Settings, risk_map: RiskMap, person_count: Callable[[], int]) -> None:
        self.s, self.map, self._person_count = settings, risk_map, person_count
        self._lock = threading.Lock()
        self.running = True
        self.speed = 1.0
        self.reset_state()

    def reset_state(self) -> None:
        self.tick = 0
        self.battery = 100.0
        self._cmd: Optional[str] = None
        self._ticks_left = 0
        self._obs_ticks = 0
        self.latest: Optional[Telemetry] = None

    # ------------------------------------------------------------ control
    def pause(self) -> None:
        self.running = False

    def resume(self) -> None:
        self.running = True

    def reset(self) -> None:
        with self._lock:
            self.reset_state()
            self.map.set_pose(self.map.rows - 1, 0, 0)

    def set_speed(self, speed: float) -> None:
        if speed not in (0.5, 1.0, 2.0):
            raise ValueError("Speed must be 0.5, 1 or 2.")
        self.speed = speed

    @property
    def interval_s(self) -> float:
        return self.s.simulation_tick_ms / 1000.0 / self.speed

    def command(self, cmd: str) -> tuple[bool, str]:
        """Execute a movement command on the simulated rover."""
        with self._lock:
            if cmd == "MOVE:STOP":
                self._cmd, self._ticks_left = None, 0
                return True, "Simulated rover stopped."
            if cmd == "MOVE:FORWARD" and self.map.has_physical_obstacle(*self.map.cell_ahead()):
                self._obs_ticks = 8
                return False, "Simulated obstacle ahead. Forward refused."
            if cmd == "MOVE:BACKWARD":
                p = self.map.pose
                dr, dc = DELTAS[(p.heading + 2) % 4]
                if self.map.has_physical_obstacle(p.row + dr, p.col + dc):
                    self._obs_ticks = 8
                    return False, "Simulated obstacle behind. Backward refused."
            self._cmd, self._ticks_left = cmd, MOVE_TICKS[cmd]
            return True, f"Simulated rover executing {cmd}."

    # ------------------------------------------------------------ simulation step
    def _free_cells(self, turn: int) -> int:
        p = self.map.pose
        dr, dc = DELTAS[(p.heading + turn) % 4]
        n, r, c = 0, p.row + dr, p.col + dc
        while n < 3 and not self.map.has_physical_obstacle(r, c):
            n += 1; r += dr; c += dc
        return n

    def _ir(self, turn: int, noise: int = 12) -> int:
        free = self._free_cells(turn)
        return max(40, int(IR_CLEAR * min(1.0, (free + 0.35) / 3.0)) + random.randint(-noise, noise))

    def step(self) -> Telemetry:
        """Advance one tick and return a simulated telemetry sample."""
        with self._lock:
            self.tick += 1
            self.battery = max(5.0, self.battery - 0.01)
            if self._cmd:
                self._ticks_left -= 1
                if self._ticks_left <= 0:
                    if not self.map.apply_pose_command(self._cmd):
                        self._obs_ticks = 8
                    self._cmd = None
            if self._obs_ticks > 0:
                self._obs_ticks -= 1
            p = self.map.pose
            sample = self.map.sample(p.row, p.col)
            temp_c = 27.0 + 50.0 * sample["thermal"] + random.uniform(-0.3, 0.3)
            hum = 45.0 - 25.0 * sample["thermal"] + random.uniform(-0.5, 0.5)
            smoke = int(self.s.smoke_baseline + sample["smoke"] * (self.s.smoke_high - self.s.smoke_baseline) + random.randint(-8, 8))
            center, right = self._ir(0), self._ir(0, 20)
            obs = min(center, right) < IR_OBSTACLE_BELOW or self._obs_ticks > 0
            local_risk = max(max(0.0, min(100.0, (temp_c - 30) / 30 * 100)), max(0.0, min(100.0, (smoke - 200) / 400 * 100)), 60.0 if obs else 0.0)
            self.latest = Telemetry(
                left_ir=self._ir(-1), center_ir=center, right_ir=right, side_ir=self._ir(1),
                temperature_tenths=int(round(temp_c * 10)), humidity_tenths=int(round(hum * 10)), smoke_value=max(0, smoke),
                obstacle_detected=obs, movement=LETTER.get(self._cmd or "", "S"),  # type: ignore[arg-type]
                risk_score=int(round(local_risk)), person_count=self._person_count(), timestamp=utcnow(), source="SIMULATED")
            return self.latest
