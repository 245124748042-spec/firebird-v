"""Sends a planned route to FireBird one high-level command at a time and replans when something changes."""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Callable, Optional

from alert_service import AlertService
from config import Settings
from rair_planner import plan_route
from risk_map import DELTAS, RiskMap, coordinate
from schemas import PlannedRoute, Telemetry

logger = logging.getLogger("firebird.route")


class CommandTracker:
    """Detects when FireBird has finished a command (telemetry MOVE is back to S).
    In LIVE mode it also dead-reckons the rover pose; in simulation the simulator moves the rover itself."""
    MIN_WAIT_S = 1.0

    def __init__(self, risk_map: RiskMap) -> None:
        self.map = risk_map
        self.pending: Optional[str] = None
        self.sent_at = 0.0
        self.apply_pose = False
        self.require_encoder_ack = False
        self.encoder_baseline: Optional[tuple[int, int]] = None
        self.latest_encoders: Optional[tuple[int, int]] = None
        self.seq = 0

    def note_sent(self, cmd: str, apply_pose: bool, require_encoder_ack: bool = False) -> None:
        if cmd == "MOVE:STOP":
            self.pending = None
            self.require_encoder_ack = False
            self.encoder_baseline = None
            return
        self.pending, self.sent_at, self.apply_pose = cmd, time.monotonic(), apply_pose
        self.require_encoder_ack = require_encoder_ack
        self.encoder_baseline = self.latest_encoders

    def on_telemetry(self, tel: Telemetry, apply_command_pose: bool = True) -> None:
        if tel.left_encoder_count is not None and tel.right_encoder_count is not None:
            self.latest_encoders = (tel.left_encoder_count, tel.right_encoder_count)
        encoder_confirmed = bool(
            self.encoder_baseline and self.latest_encoders
            and self.latest_encoders[0] != self.encoder_baseline[0]
            and self.latest_encoders[1] != self.encoder_baseline[1]
        )
        if (self.pending and time.monotonic() - self.sent_at >= self.MIN_WAIT_S and tel.movement == "S"
                and (not self.require_encoder_ack or encoder_confirmed)):
            if self.apply_pose and apply_command_pose:
                self.map.apply_pose_command(self.pending)
            self.pending = None
            self.require_encoder_ack = False
            self.encoder_baseline = None
            self.seq += 1


class RouteExecutor:
    CONFIRM_TIMEOUT_S = 10.0
    OBSTACLE_WAIT_S = 3.0

    def __init__(self, risk_map: RiskMap, settings: Settings, tracker: CommandTracker, send: Callable[[str], tuple[bool, str]],
                 telemetry: Callable[[], Optional[Telemetry]], alerts: AlertService, changed: Callable[[], None],
                 safety_check: Optional[Callable[[], Optional[str]]] = None) -> None:
        self.map, self.s, self.tracker, self._send, self._tel, self.alerts, self._changed = risk_map, settings, tracker, send, telemetry, alerts, changed
        self._safety_check = safety_check or (lambda: None)
        self.route: Optional[PlannedRoute] = None
        self.original_route: Optional[PlannedRoute] = None
        self.replan_count = 0
        self.goal: Optional[tuple[int, int]] = None
        self.alpha, self.risk_aware = 1.5, True
        self.idx = 0
        self.running = False
        self.paused = False
        self.state = "IDLE"  # IDLE | FOLLOWING | STOPPING | PAUSED | COMPLETE | BLOCKED | FAILED
        self.slow = False
        self._awaiting = False
        self._await_seq = 0
        self._sent_at = 0.0
        self._last_done = 0.0
        self._obs_wait: Optional[float] = None
        self._expected_pose: Optional[tuple[int, int, int]] = None
        self._awaiting_stop_command_id: Optional[int] = None
        self._stop_after_ack_state: Optional[str] = None
        self.version = 0

    # ------------------------------------------------------------ control
    def _set(self, state: str) -> None:
        self.state = state
        self.version += 1
        self._changed()

    def start(self, route: PlannedRoute, goal: tuple[int, int], alpha: float, risk_aware: bool) -> None:
        self.route, self.original_route, self.goal, self.alpha, self.risk_aware = route, route, goal, alpha, risk_aware
        self.replan_count = 0
        self.idx, self.running, self.paused, self._awaiting, self._obs_wait = 0, True, False, False, None
        p = self.map.pose
        self._expected_pose = (p.row, p.col, p.heading)
        self._awaiting_stop_command_id = None
        self._stop_after_ack_state = None
        self._set("FOLLOWING")
        self.alerts.add("INFO", "PATH", f"Route following started ({len(route.commands) - 1} moves)", coordinate(*goal), "Keep emergency stop available")

    def pause(self, reason: str) -> None:
        if self.running and not self.paused:
            ok, msg = self._send("MOVE:STOP")
            self.paused = True
            if ok:
                if self._wait_for_pi_stop(msg, "PAUSED"):
                    self._set("STOPPING")
                    self.alerts.add("WARNING", "PATH", f"Route paused; waiting for Pi stop acknowledgement: {reason}", coordinate(self.map.pose.row, self.map.pose.col), "Resume when safe", dedupe_s=0)
                    return
                self._set("PAUSED")
                self.alerts.add("WARNING", "PATH", f"Route paused: {reason}", coordinate(self.map.pose.row, self.map.pose.col), "Resume when safe", dedupe_s=0)
            else:
                self.running = self.paused = False
                self._set("FAILED")
                self.alerts.add("CRITICAL", "PATH", f"Navigation failed: {reason}; STOP could not be sent ({msg})", "-", "Restore communication and verify the rover is stopped", dedupe_s=0)

    def resume(self) -> bool:
        if self.running and self.paused:
            # A pause may have stopped the rover part-way through a cell. Replan
            # from the latest encoder pose instead of blindly repeating a full step.
            return self.replan()
        return False

    def stop(self, reason: str = "Route stopped") -> None:
        was = self.running
        if was:
            ok, msg = self._send("MOVE:STOP")
            if not ok:
                self.running = self.paused = self._awaiting = False
                self._set("FAILED")
                self.alerts.add("CRITICAL", "PATH", f"Navigation stop could not be sent ({msg})", "-", "Restore communication and verify the rover is stopped", dedupe_s=0)
                return
            if self._wait_for_pi_stop(msg, "IDLE"):
                self.paused = True
                self._set("STOPPING")
                return
            self.alerts.add("INFO", "PATH", reason, "-", dedupe_s=0)
        self.running = self.paused = self._awaiting = False
        self._set("IDLE")

    def _wait_for_pi_stop(self, message: str, final_state: str) -> bool:
        if not message.startswith("PI_QUEUE:"):
            return False
        try:
            self._awaiting_stop_command_id = int(message.partition(":")[2])
        except ValueError:
            return False
        self._stop_after_ack_state = final_state
        self._sent_at = time.monotonic()
        self._awaiting = False
        return True

    def reset_for_route(self) -> bool:
        """Discard any old executor route when the user plans a new destination."""
        if self.state in {"FAILED", "STOPPING"}:
            return False
        if self.running:
            self.stop("Navigation stopped because a new route was planned")
            if self.state in {"FAILED", "STOPPING"}:
                return False
        self.route = None
        self.goal = None
        self.idx = 0
        self._awaiting = self.paused = False
        self._expected_pose = None
        self._awaiting_stop_command_id = None
        self._stop_after_ack_state = None
        self._set("IDLE")
        return True

    def clear_failed_after_stop(self) -> None:
        if self.state == "FAILED" and not self.running:
            self.route = None
            self.goal = None
            self.idx = 0
            self._awaiting = self.paused = False
            self._awaiting_stop_command_id = None
            self._stop_after_ack_state = None
            self._set("IDLE")

    def on_bridge_command_ack(self, command_id: int, accepted: bool, error: Optional[str]) -> None:
        if command_id == self._awaiting_stop_command_id:
            self._awaiting_stop_command_id = None
            if accepted:
                final_state, self._stop_after_ack_state = self._stop_after_ack_state, None
                if final_state == "PAUSED":
                    self.running = self.paused = True
                    self._set("PAUSED")
                elif final_state == "REPLAN":
                    self.paused = True
                    self.replan()
                elif final_state == "IDLE":
                    self.running = self.paused = False
                    self._set("IDLE")
                else:
                    self.running = self.paused = False
                    self.idx += 1
                    self._set("COMPLETE")
                    self.alerts.add("INFO", "PATH", "Goal reached; Raspberry Pi confirmed the stop command was written.",
                                    coordinate(self.map.pose.row, self.map.pose.col), dedupe_s=0)
            else:
                self.running = self.paused = False
                self._stop_after_ack_state = None
                self._set("FAILED")
                self.alerts.add("CRITICAL", "PATH", f"Navigation failed: Pi rejected STOP ({error or 'unknown error'})", "-",
                                "Restore communication and verify the rover is stopped", dedupe_s=0)
        elif not accepted and self.running:
            self.pause(f"Raspberry Pi serial write failed: {error or 'unknown error'}")

    # ------------------------------------------------------------ replanning
    def replan(self) -> bool:
        """Recalculate from the rover's current cell to the same goal. Returns True if a route was found."""
        if not self.goal:
            return False
        p = self.map.pose
        grid = self.map.cost_grid()
        route = plan_route(grid, (p.row, p.col), self.goal, p.heading, self.alpha, self.risk_aware, self.s.risk_cost_scale)
        if route.found:
            self.route, self.idx, self.paused, self._awaiting = route, 0, False, False
            self.replan_count += 1
            self._expected_pose = (p.row, p.col, p.heading)
            self._set("FOLLOWING")
            self.alerts.add("INFO", "PATH", f"Route replanned: {len(route.commands) - 1} moves, risk {route.total_risk}", coordinate(*self.goal), dedupe_s=0)
            return True
        self.running = self.paused = False
        self._set("BLOCKED")
        self.alerts.add("CRITICAL", "PATH", "Destination blocked – Waiting for a safe path.", coordinate(*self.goal), "Keep the rover stopped and clear the obstacle", dedupe_s=0)
        return False

    def _advance_expected_pose(self, cmd: str) -> None:
        if self._expected_pose is None:
            return
        row, col, heading = self._expected_pose
        if cmd == "MOVE:LEFT":
            heading = (heading - 1) % 4
        elif cmd == "MOVE:RIGHT":
            heading = (heading + 1) % 4
        elif cmd in {"MOVE:FORWARD", "MOVE:BACKWARD"}:
            dr, dc = DELTAS[heading]
            sign = 1 if cmd == "MOVE:FORWARD" else -1
            row, col = row + sign * dr, col + sign * dc
        self._expected_pose = (row, col, heading)

    def handle_obstacle(self) -> None:
        """FireBird reported OBS:1. Mark the cell ahead as blocked, pause, then replan."""
        r, c = self.map.cell_ahead()
        if self.map.in_bounds(r, c):
            self.map.set_sensor_obstacle(r, c, True)
            self.map.latch_sensor_obstacle(r, c)
        where = coordinate(r, c) if self.map.in_bounds(r, c) else "-"
        ok, msg = self._send("MOVE:STOP")
        if self.running:
            if not ok:
                self.running = self.paused = self._awaiting = False
                self._set("FAILED")
                self.alerts.add("CRITICAL", "PATH", f"Obstacle stop failed: {msg}", where, "Restore communication and verify the rover is stopped", dedupe_s=0)
                return
            self.paused = True
            self.alerts.add("WARNING", "OBSTACLE", "Obstacle detected – Replanning route.", where, "Stopped; finding a safe route", dedupe_s=0)
            if self._wait_for_pi_stop(msg, "REPLAN"):
                self._set("STOPPING")
                return
            self.replan()
        else:
            self.alerts.add("WARNING", "OBSTACLE", "Obstacle detected – Replanning route.", where, "Choose another direction", dedupe_s=0)

    # ------------------------------------------------------------ loop
    def status(self) -> dict:
        n = len(self.route.commands) if self.route else 0
        return {"state": self.state, "running": self.running, "paused": self.paused, "index": self.idx, "total": n,
                "goal": coordinate(*self.goal) if self.goal else None, "alpha": self.alpha, "riskAware": self.risk_aware,
                "path": self.route.cells if self.route else [],
                "originalPath": self.original_route.cells if self.original_route else [],
                "replanCount": self.replan_count,
                "nextCommand": self.route.commands[self.idx] if self.route and self.idx < n else None, "version": self.version}

    def tick(self) -> None:
        if not self.running or not self.route:
            return
        now = time.monotonic()
        if self._awaiting_stop_command_id is not None:
            if now - self._sent_at > 3.0:
                self._awaiting_stop_command_id = None
                self._stop_after_ack_state = None
                self.running = self.paused = False
                self._set("FAILED")
                self.alerts.add("CRITICAL", "PATH", "Pi did not acknowledge the stop command; navigation failed.", "-",
                                "Restore communication and verify the rover is stopped", dedupe_s=0)
            return
        if self.paused:
            return
        blocked = self._safety_check()
        if blocked:
            self.pause(blocked)
            return
        if self._awaiting:
            if self.tracker.seq > self._await_seq:
                cmd = self.route.commands[self.idx]
                self._advance_expected_pose(cmd)
                self._awaiting, self._last_done = False, now
                actual = (self.map.pose.row, self.map.pose.col, self.map.pose.heading)
                if actual != self._expected_pose:
                    self.alerts.add("WARNING", "PATH", "Encoder pose differs from the planned step; recalculating from the measured rover position.",
                                    coordinate(self.map.pose.row, self.map.pose.col), "Route is being corrected", dedupe_s=0)
                    self.replan()
                    return
                self.idx += 1
                self.version += 1
            elif now - self._sent_at > self.CONFIRM_TIMEOUT_S:
                self._awaiting = False
                self.pause("FireBird did not confirm the last command")
            return
        if self.idx >= len(self.route.commands):
            self.running = False
            self._set("COMPLETE")
            return
        if self.slow and now - self._last_done < 2.5:
            return
        cmd = self.route.commands[self.idx]
        if cmd == "MOVE:STOP" and self.goal and (self.map.pose.row, self.map.pose.col) != self.goal:
            self.alerts.add("WARNING", "PATH", "Measured rover position has not reached the destination; recalculating before stopping.",
                            coordinate(self.map.pose.row, self.map.pose.col), "Route is being corrected", dedupe_s=0)
            self.replan()
            return
        if cmd == "MOVE:FORWARD":
            tel = self._tel()
            if tel and tel.obstacle_detected:  # FireBird has final safety authority: never push forward into OBS:1
                self._obs_wait = self._obs_wait or now
                if now - self._obs_wait > self.OBSTACLE_WAIT_S:
                    self._obs_wait = None
                    self.handle_obstacle()
                return
            self._obs_wait = None
            ahead = self.map.cell_ahead()
            if self.map.is_blocked(*ahead):
                self.alerts.add("WARNING", "PATH", "Next cell became blocked. Replanning.", coordinate(*ahead) if self.map.in_bounds(*ahead) else "-", dedupe_s=1)
                self.replan()
                return
        ok, msg = self._send(cmd)
        if not ok:
            self.pause(msg)
            return
        if cmd == "MOVE:STOP":
            if msg.startswith("PI_QUEUE:"):
                if self._wait_for_pi_stop(msg, "COMPLETE"):
                    self._set("STOPPING")
                    return
                self.running = self.paused = False
                self._set("FAILED")
                return
            self.idx += 1
            self.running = False
            self._set("COMPLETE")
            self.alerts.add("INFO", "PATH", "Goal reached", coordinate(self.map.pose.row, self.map.pose.col), dedupe_s=0)
            return
        self._awaiting, self._await_seq, self._sent_at = True, self.tracker.seq, now

    async def run(self) -> None:
        while True:
            await asyncio.sleep(0.1)
            try:
                self.tick()
            except Exception:  # noqa: BLE001
                logger.exception("route executor error")
