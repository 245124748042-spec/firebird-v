"""FireBird PC backend: serial link, YOLO person detection, risk map, RAIR-inspired planner, REST + WebSocket API."""
from __future__ import annotations

import asyncio
import logging
import math
import threading
import time
from collections import deque
from contextlib import asynccontextmanager
from typing import Any, Optional

import numpy as np
import uvicorn
from fastapi import Body, FastAPI, HTTPException, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from starlette.concurrency import run_in_threadpool

from alert_service import AlertService
from config import Settings, get_settings
from rair_planner import heading_index, plan_route
from risk_map import HEADINGS, Overlay, RiskMap, coordinate, parse_coordinate, risk_level
from odometry import (DifferentialDriveOdometry, calibration_is_valid,
                      command_pose_enabled, map_heading_to_radians)
from route_executor import CommandTracker, RouteExecutor
from schemas import (AckRequest, CameraInfo, CellIndex, CellUpdate, CommandRequest, MapSnapshot, ModelInfo, PersonDetection, PersonStartRequest,
                     PlannedRoute, ResizeRequest, RoverInfo, SafetyActionRequest, SensorHealth, SerialConnectRequest, SerialInfo,
                     SimulationControl, StatusResponse, Telemetry, RouteRequest, RaspberryPiInfo, utcnow)
from serial_service import SerialService, parse_telemetry
from simulation_service import SimulationService
from vision_service import VisionService

logger = logging.getLogger("firebird")


class ConnectionManager:
    """Keeps the set of dashboard WebSocket clients and broadcasts safely to all of them."""

    def __init__(self) -> None:
        self._clients: set[WebSocket] = set()
        self._lock = asyncio.Lock()

    @property
    def count(self) -> int:
        return len(self._clients)

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        async with self._lock:
            self._clients.add(ws)

    async def disconnect(self, ws: WebSocket) -> None:
        async with self._lock:
            self._clients.discard(ws)

    async def broadcast(self, message: dict) -> None:
        async with self._lock:
            clients = list(self._clients)
        dead = []
        for ws in clients:
            try:
                await asyncio.wait_for(ws.send_json(message), timeout=2.0)
            except Exception:  # noqa: BLE001  a slow or closed client must not stop the others
                dead.append(ws)
        if dead:
            async with self._lock:
                for ws in dead:
                    self._clients.discard(ws)


class Context:
    """Holds every service. Lives on app.state so there is no module-level mutable state."""

    def __init__(self, settings: Settings, loop: asyncio.AbstractEventLoop) -> None:
        self.settings, self.loop = settings, loop
        self.map = RiskMap(settings)
        self.alerts = AlertService()
        self.serial = SerialService(settings.serial_port, settings.baud_rate)
        self.vision = VisionService(settings.model_file, settings.camera_index, settings.confidence_threshold,
                                    settings.person_count_stable_frames, lambda n: loop.call_soon_threadsafe(self.on_person_count, n))
        self.sim = SimulationService(settings, self.map, self.person_count)
        self.tracker = CommandTracker(self.map)
        self.executor = RouteExecutor(self.map, settings, self.tracker, lambda cmd: self.send_move(cmd, "executor"), self.telemetry, self.alerts,
                                      lambda: None, lambda: self.navigation_block_reason(check_start=False))
        self.manager = ConnectionManager()
        self.live_latest: Optional[Telemetry] = None
        self.pi_latest: Optional[Telemetry] = None
        self.pi_last_rx: Optional[float] = None
        self.pi_last_rx_at = None
        self.pi_messages_ok = 0
        self.pi_person_count: Optional[int] = None
        self.pi_person_count_at = None
        self.emergency_stop_latched = False
        self._pi_command_lock = threading.Lock()
        self._pi_command_id = 0
        self._pi_pending_command: Optional[dict[str, Any]] = None
        self._pi_dispatch_pending: dict[int, dict[str, Any]] = {}
        self._pi_superseded_commands: set[int] = set()
        self._pi_failure_recovery_command_id: Optional[int] = None
        self.raw_log: deque[dict] = deque(maxlen=80)
        self.mode_now = "SIMULATION"
        self.last_route: Optional[PlannedRoute] = None
        self.last_goal: Optional[tuple[int, int]] = None
        self._prev_obs = False
        self._obstacle_clear_samples = 0
        self._retry_blocked_after_obstacle = False
        self._prev_robot_flags = 0
        self._last_map_version = -1
        self._last_exec_version = -1
        self._odometry = DifferentialDriveOdometry()
        self._odom_origin: Optional[tuple[int, int]] = None
        self.serial.on_telemetry = lambda tel, raw: loop.call_soon_threadsafe(self.on_live_telemetry, tel, raw)
        self.serial.on_disconnect = lambda reason: loop.call_soon_threadsafe(self.on_serial_lost, reason)
        self.alerts.on_new = lambda a: self.emit("alert", a)

    # ------------------------------------------------------------ mode / state
    @property
    def mode(self) -> str:
        """LIVE only while a connected FireBird source is delivering recent valid telemetry."""
        if self.settings.raspberry_pi_mode:
            pi_live = self.pi_last_rx is not None and time.monotonic() - self.pi_last_rx < self.settings.live_timeout_s
            return "LIVE" if pi_live else "SIMULATION"
        age = self.serial.seconds_since_rx()
        serial_live = self.serial.is_connected() and age is not None and age < self.settings.live_timeout_s
        return "LIVE" if serial_live else "SIMULATION"

    def telemetry(self) -> Optional[Telemetry]:
        if self.settings.raspberry_pi_mode:
            return self.pi_latest or self.sim.latest
        if self.mode != "LIVE":
            return self.sim.latest
        return self.live_latest

    def person_count(self) -> int:
        if self.settings.raspberry_pi_mode and self.pi_person_count is not None:
            return self.pi_person_count
        return self.vision.count if self.vision.camera_active else self.map.user_person_count()

    def check_mode(self) -> None:
        m = self.mode
        if m == self.mode_now:
            return
        old, self.mode_now = self.mode_now, m
        self.executor.stop("Route stopped because the data mode changed") if self.executor.running else None
        if m == "LIVE":
            source = "Raspberry Pi Wi-Fi" if self.settings.raspberry_pi_mode else "FireBird serial"
            self.alerts.add("INFO", "SYSTEM", f"LIVE MODE: {source} telemetry is being received. Simulation values stopped.", dedupe_s=0)
        else:
            action = "Check Raspberry Pi Wi-Fi forwarding and backend URL" if self.settings.raspberry_pi_mode else "Check cable, COM port and baud rate"
            self.alerts.add("WARNING", "SYSTEM", "FireBird telemetry lost or not connected. Switched to SIMULATION MODE.", "-", action, dedupe_s=0)
        logger.info("Mode %s -> %s", old, m)
        self.emit("status", self.build_status())

    # ------------------------------------------------------------ broadcasting
    def emit(self, kind: str, payload: Any, raw: Optional[str] = None) -> None:
        """Queue a WebSocket broadcast. Safe to call from any thread."""
        if self.manager.count == 0:
            return
        msg: dict = {"type": kind, "data": jsonable_encoder(payload, by_alias=True), "timestamp": time.time()}
        if raw is not None:
            msg["raw"] = raw
        self.loop.call_soon_threadsafe(lambda: self.loop.create_task(self.manager.broadcast(msg)))

    # ------------------------------------------------------------ telemetry handling
    def on_live_telemetry(self, tel: Telemetry, raw: str) -> None:
        self.live_latest = tel
        self.raw_log.append({"timestamp": tel.timestamp.isoformat(), "line": raw})
        self.check_mode()
        self.process_telemetry(tel, live=True)
        self.emit("telemetry", tel, raw)

    def on_pi_telemetry(self, tel: Telemetry, raw: str, yolo_count: Optional[int]) -> None:
        """Accept a validated FireBird frame forwarded by the Raspberry Pi."""
        self.pi_latest = tel
        self.pi_last_rx = time.monotonic()
        self.pi_last_rx_at = tel.timestamp
        self.pi_messages_ok += 1
        self.pi_person_count = yolo_count
        self.pi_person_count_at = tel.timestamp if yolo_count is not None else None
        if yolo_count is not None:
            self._update_pi_person_risk(yolo_count)
        else:
            self.map.set_camera_presence(False, None)
        self.live_latest = tel
        self.raw_log.append({"timestamp": tel.timestamp.isoformat(), "line": raw})
        self.check_mode()
        self.process_telemetry(tel, live=True)
        self.emit("telemetry", tel, raw)

    def on_pi_person_count(self, count: int) -> None:
        """Record count-only updates from the Pi detector; telemetry remains its own source of LIVE status."""
        self.pi_person_count = count
        self.pi_person_count_at = utcnow()
        self._update_pi_person_risk(count)
        if count > 0 and self.executor.running and self.vision.safety_action == "stop":
            self.executor.pause("person detected by Raspberry Pi YOLO")
        if self.pi_latest is not None:
            self.pi_latest = self.pi_latest.model_copy(update={"person_count": count})
        self.emit("person", PersonDetection(person_count=count, count=count, camera_active=False,
                                             model_loaded=None, model_path="/home/pi/person_detection/models/firebird_person_yolov8n_best.onnx"))

    def _update_pi_person_risk(self, count: int) -> None:
        """Localize count-only Pi detection approximately to the cell in front of the rover."""
        ahead = self.map.cell_ahead()
        cell = ahead if self.map.in_bounds(*ahead) else None
        self.map.set_camera_presence(count > 0, cell)

    def navigation_block_reason(self, *, check_start: bool = True, allow_obstacle_escape: bool = False) -> Optional[str]:
        """Fail closed unless the selected serial owner has fresh calibrated feedback."""
        if self.emergency_stop_latched:
            return "Emergency stop is latched; explicitly reset it after checking the rover"
        if self.settings.raspberry_pi_mode:
            age = None if self.pi_last_rx is None else time.monotonic() - self.pi_last_rx
            tel = self.pi_latest
            connected = age is not None and age < self.settings.live_timeout_s
            if not connected:
                return "Raspberry Pi telemetry connection is not live"
            with self._pi_command_lock:
                expired_ids = [command_id for command_id, item in self._pi_dispatch_pending.items()
                               if time.monotonic() - item["created"] > 1.5]
                for command_id in expired_ids:
                    self._pi_dispatch_pending.pop(command_id, None)
                    self._pi_superseded_commands.discard(command_id)
            if expired_ids:
                return "Raspberry Pi did not acknowledge a movement command"
        else:
            if self.mode != "LIVE" or not self.serial.is_connected():
                return "FireBird serial connection is not live"
            age = self.serial.seconds_since_rx()
            tel = self.live_latest
        if age is None or age >= min(self.settings.live_timeout_s, 1.5):
            return "FireBird telemetry is stale"
        if tel is None:
            return "No FireBird telemetry is available"
        if tel.left_encoder_count is None or tel.right_encoder_count is None:
            return "Encoder feedback is unavailable; navigation requires both encoder counts"
        if not calibration_is_valid(self.settings.wheel_diameter_m, self.settings.wheel_track_m,
                                    self.settings.encoder_pulses_per_revolution, self.settings.map_cell_size_m):
            return "Odometry calibration is incomplete; configure measured wheel, encoder and map-cell values"
        if tel.dht_ok is not True or tel.smoke_value <= 0:
            return "Required environmental sensor health is unavailable"
        if check_start and tel.movement != "S":
            return "FireBird reports movement in progress; wait until it is stopped before starting navigation"
        if tel.obstacle_detected and not allow_obstacle_escape:
            return "Obstacle is currently detected"
        if self.person_count() > 0 and self.vision.safety_action == "stop":
            return "Person detected; movement is blocked by the active person safety action"
        p = self.map.pose
        critical_environment = (tel.temperature_tenths / 10.0 >= 55.0 or tel.smoke_value >= self.settings.smoke_high)
        if tel.risk_score >= 75 or self.map.sample(p.row, p.col)["score"] >= 75 or tel.flags & 0x07 or critical_environment:
            return "Critical hazard or FireBird safety-stop flag is active"
        return None

    def queue_pi_command(self, command: str) -> tuple[bool, str]:
        """Queue one high-level command for the Pi's existing serial-owning process."""
        with self._pi_command_lock:
            if self._pi_pending_command is not None and command != "MOVE:STOP":
                return False, "A Raspberry Pi serial command is already awaiting dispatch."
            if command == "MOVE:STOP":
                # Retire every outstanding movement before publishing STOP. If the
                # Pi already claimed one, its later ack must be rejected so the Pi
                # immediately issues its local best-effort C:S and then polls STOP.
                for command_id, item in list(self._pi_dispatch_pending.items()):
                    if item["command"] != "MOVE:STOP":
                        self._pi_superseded_commands.add(command_id)
                        if self._pi_pending_command and self._pi_pending_command["commandId"] == command_id:
                            self._pi_pending_command = None
            self._pi_command_id += 1
            item = {"commandId": self._pi_command_id, "command": command, "created": time.monotonic()}
            self._pi_pending_command = item
            self._pi_dispatch_pending[item["commandId"]] = item
        return True, f"PI_QUEUE:{item['commandId']}"

    def take_pi_command(self) -> Optional[dict[str, Any]]:
        """One-time claim prevents stale polls from replaying a movement command."""
        expired = False
        with self._pi_command_lock:
            item = self._pi_pending_command
            if item is None:
                return None
            if item["command"] != "MOVE:STOP" and time.monotonic() - item["created"] > 1.0:
                self._pi_pending_command = None
                self._pi_dispatch_pending.pop(item["commandId"], None)
                expired = True
            else:
                self._pi_pending_command = None
                age_ms = 0 if item["command"] == "MOVE:STOP" else int((time.monotonic() - item["created"]) * 1000)
                result = {"commandId": item["commandId"], "command": item["command"],
                          "ageMs": age_ms, "ttlMs": 1000}
        if expired:
            if self.executor.running:
                self.executor.pause("Pi command expired before serial dispatch")
            return None
        return result

    def acknowledge_pi_command(self, command_id: int, accepted: bool, error: Optional[str]) -> bool:
        with self._pi_command_lock:
            if command_id in self._pi_superseded_commands:
                self._pi_superseded_commands.discard(command_id)
                self._pi_dispatch_pending.pop(command_id, None)
                return False
            item = self._pi_dispatch_pending.pop(command_id, None)
        if item is None:
            return False
        self.executor.on_bridge_command_ack(command_id, accepted, error)
        if command_id == self._pi_failure_recovery_command_id:
            self._pi_failure_recovery_command_id = None
            if accepted and self.pi_latest and self.pi_latest.movement == "S" and self.mode == "LIVE":
                self.executor.clear_failed_after_stop()
        return True

    def on_serial_lost(self, reason: str) -> None:
        self.alerts.add("CRITICAL", "SYSTEM", f"Serial disconnected: {reason}", "-", "Reconnect FireBird, then press Connect Robot", dedupe_s=0)
        self.check_mode()

    def _update_odometry(self, tel: Telemetry) -> None:
        """Integrate encoder deltas and project them into the existing map frame."""
        left, right = tel.left_encoder_count, tel.right_encoder_count
        if left is None or right is None:
            return
        p = self.map.pose
        initial_heading = map_heading_to_radians(p.heading)
        pose, initialized, project_pose = self._odometry.update(
            left, right, tel.movement,
            wheel_diameter_m=self.settings.wheel_diameter_m,
            wheel_track_m=self.settings.wheel_track_m,
            pulses_per_revolution=self.settings.encoder_pulses_per_revolution,
            initial_heading_rad=initial_heading,
        )
        if initialized:
            p = self.map.pose
            self._odom_origin = (p.row, p.col)
        if self._odom_origin and project_pose:
            self.map.set_odometry_pose(pose.x_m, pose.y_m, pose.heading_rad,
                                       self.settings.map_cell_size_m, *self._odom_origin)

    def process_telemetry(self, tel: Telemetry, live: bool) -> None:
        previous_cost = self.map.cost_grid() if live and self.executor.running else None
        p = self.map.pose
        here = coordinate(p.row, p.col)
        encoder_sample = (live and tel.left_encoder_count is not None and tel.right_encoder_count is not None)
        odometry_enabled = calibration_is_valid(
            self.settings.wheel_diameter_m, self.settings.wheel_track_m,
            self.settings.encoder_pulses_per_revolution, self.settings.map_cell_size_m,
        )
        encoder_odometry_active = encoder_sample and odometry_enabled
        if encoder_odometry_active:
            self._update_odometry(tel)
        else:
            # When calibration or either count is unavailable, use the established
            # command tracker and ensure the next valid sample is baseline-only.
            self._odometry.reset_baseline()
            self._odom_origin = None
        self.tracker.on_telemetry(
            tel, apply_command_pose=command_pose_enabled(encoder_sample, odometry_enabled))
        p = self.map.pose
        here = coordinate(p.row, p.col)
        if live:
            reported_risk = tel.total_risk if tel.total_risk is not None else tel.risk_score
            self.map.mark_sensor(p.row, p.col, tel.temperature_tenths / 10.0, tel.smoke_value, reported_risk)
            # Firmware's obstacle flag is derived from its five IR sensors. The
            # forward cell is a temporary sensor observation, cleared on the next
            # telemetry frame that reports no obstacle.
            ahead = self.map.cell_ahead()
            if self.map.in_bounds(*ahead):
                self.map.set_sensor_obstacle(*ahead, tel.obstacle_detected)
            if tel.obstacle_detected:
                self.map.latch_sensor_obstacle(*ahead)
                self._obstacle_clear_samples = 0
                self._retry_blocked_after_obstacle = True
            else:
                self._obstacle_clear_samples += 1
                if self._obstacle_clear_samples >= 5:
                    self.map.clear_sensor_obstacles()
            if previous_cost is not None and self.executor.running:
                current_cost = self.map.cost_grid()
                material_change = (np.max(np.abs(current_cost.risk01 - previous_cost.risk01)) >= 0.15
                                   or np.any(current_cost.blocked & ~previous_cost.blocked))
                if material_change:
                    self.executor.replan()
        # obstacle safety first
        if tel.obstacle_detected and not self._prev_obs:
            self.executor.handle_obstacle()
        self._prev_obs = tel.obstacle_detected
        if (live and self.executor.state == "BLOCKED" and self._retry_blocked_after_obstacle
                and not tel.obstacle_detected and not self.map.sensor_obstacles
                and not self.map.latched_sensor_obstacles and self.executor.goal):
            self._retry_blocked_after_obstacle = False
            self.executor.replan()
        # environment alerts
        t, s, base, high = tel.temperature_tenths / 10.0, tel.smoke_value, self.settings.smoke_baseline, self.settings.smoke_high
        flags = tel.flags
        if live and flags & (1 << 0):
            self.alerts.add("WARNING", "ENVIRONMENT", "FireBird hazard flag is active.", here, "Check the rover and hazard area", dedupe_s=15)
        if live and flags & (1 << 1):
            self.alerts.add("CRITICAL", "ENVIRONMENT", "FireBird smoke alarm flag is active.", here, "Move away from the area", dedupe_s=15)
        if t >= 55:
            self.alerts.add("CRITICAL", "ENVIRONMENT", f"Temperature high: {t:.1f} °C", here, "Move away from the area", dedupe_s=15)
        elif t >= 40:
            self.alerts.add("WARNING", "ENVIRONMENT", f"Temperature elevated: {t:.1f} °C", here, "Monitor the area", dedupe_s=15)
        if live and flags & (1 << 4):
            pass  # Firmware indicates the smoke sensor is still warming up.
        elif s >= high:
            self.alerts.add("CRITICAL", "ENVIRONMENT", f"Smoke level high: {s}", here, "Move away from the area", dedupe_s=15)
        elif s >= base + 0.5 * (high - base):
            self.alerts.add("WARNING", "ENVIRONMENT", f"Smoke level rising: {s}", here, "Monitor the area", dedupe_s=15)
        local_risk = self.map.sample(p.row, p.col)["score"]
        if tel.risk_score >= 75 or local_risk >= 75:
            self.alerts.add("CRITICAL", "ENVIRONMENT", "Fire-risk level critical", here, "Keep rover and people away", dedupe_s=15)
        critical_environment = t >= 55 or s >= high
        if live and self.executor.running and (tel.risk_score >= 75 or local_risk >= 75 or flags & 0x07 or critical_environment):
            self.executor.pause("critical hazard or FireBird safety-stop flag")
        if live and flags & (1 << 2) and not self._prev_robot_flags & (1 << 2):
            self.alerts.add("WARNING", "PERSON", "FireBird person-stop flag is active.", here, "Keep clear until the rover reports safe to move", dedupe_s=2)
        self._prev_robot_flags = flags

    # ------------------------------------------------------------ person handling
    def on_person_count(self, n: int) -> None:
        """Called (in the event loop) when the stabilized camera count changes."""
        v = self.vision
        if v.send_to_firebird:
            if not self.settings.raspberry_pi_mode and self.mode == "LIVE" and self.serial.send_person_count(n):
                v.serial_message = f"P:{n}"
            else:
                v.serial_message = f"P:{n} (not sent: no live FireBird)"
        self.after_person_change(n)
        self.emit("person", v.status())

    def after_person_change(self, n: int) -> None:
        p = self.map.pose
        here = coordinate(p.row, p.col)
        ahead = self.map.cell_ahead()
        self.map.set_camera_presence(n > 0 and self.vision.camera_active, ahead if self.map.in_bounds(*ahead) else None)
        if n > 0:
            self.alerts.add("WARNING", "PERSON", f"Person detected. Count updated to {n}.", here, "Follow the person safety action", dedupe_s=1)
            near = self.map.persons_near_hazard(50.0)
            if near:
                self.alerts.add("CRITICAL", "PERSON", "Person detected near high-risk zone.", near[0], "Keep rover and people away", dedupe_s=5)
        act = self.vision.safety_action
        self.executor.slow = n > 0 and act == "slow"
        if n > 0 and act == "stop" and self.executor.running:
            self.executor.pause("person detected (safety action: stop)")

    # ------------------------------------------------------------ commands
    def send_move(self, cmd: str, source: str = "api") -> tuple[bool, str]:
        """Single path for every movement command. Only high-level commands are ever sent. Safety rules live here."""
        if cmd != "MOVE:STOP" and self.mode == "LIVE":
            # Apply the same fail-closed live safety gate to executor and manual
            # movement. STOP deliberately bypasses this gate.
            reason = self.navigation_block_reason(check_start=(source == "executor"),
                                                  allow_obstacle_escape=(source == "executor" and cmd in {"MOVE:LEFT", "MOVE:RIGHT"}))
            if reason:
                return False, reason
        if self.settings.raspberry_pi_mode:
            age = None if self.pi_last_rx is None else time.monotonic() - self.pi_last_rx
            if cmd != "MOVE:STOP" and (age is None or age >= min(self.settings.live_timeout_s, 1.5)):
                return False, "Raspberry Pi bridge is not receiving fresh telemetry."
            ok, message = self.queue_pi_command(cmd)
            if ok:
                self.tracker.note_sent(cmd, apply_pose=(source != "executor"), require_encoder_ack=(source == "executor"))
            return ok, message
        if source == "executor" and cmd == "MOVE:STOP":
            if not self.serial.is_connected():
                return False, "FireBird serial connection is unavailable; STOP could not be sent."
            ok = self.serial.send_command(cmd)
            if ok:
                self.tracker.note_sent(cmd, apply_pose=False)
            return ok, "STOP sent to FireBird." if ok else "Serial STOP write failed."
        if cmd == "MOVE:STOP" and self.mode != "LIVE" and self.serial.is_connected():
            # Stale telemetry must block ordinary movement, but an open serial
            # transport can still carry the existing FireBird stop command.
            ok = self.serial.send_command(cmd)
            if ok:
                self.tracker.note_sent(cmd, apply_pose=False)
            return ok, "STOP sent to FireBird." if ok else "Serial STOP write failed."
        if source == "executor" and self.mode != "LIVE":
            return False, "Navigation commands require fresh live FireBird telemetry."
        if source != "executor" and cmd != "MOVE:STOP" and self.executor.running and not self.executor.paused:
            self.executor.pause("manual command received")
        if self.mode == "LIVE":
            ok = self.serial.send_command(cmd)
            if ok:
                self.tracker.note_sent(cmd, apply_pose=True, require_encoder_ack=(source == "executor"))
            return ok, "Command sent to FireBird." if ok else "Serial write failed."
        ok, msg = self.sim.command(cmd)
        if ok:
            self.tracker.note_sent(cmd, apply_pose=False)
        return ok, msg

    # ------------------------------------------------------------ builders
    def build_status(self) -> StatusResponse:
        tel, p, mode = self.telemetry(), self.map.pose, self.mode
        live = mode == "LIVE"
        cell_score = self.map.sample(p.row, p.col)["score"]
        sensors = SensorHealth()
        if live and tel:
            dht_ok = tel.dht_ok if tel.dht_ok is not None else (tel.humidity_tenths > 0 and tel.temperature_tenths != 0)
            sensors = SensorHealth(dht22="ok" if dht_ok else "error", smoke="ok" if tel.smoke_value > 0 else "error")
        pi_live = self.settings.raspberry_pi_mode and self.pi_last_rx is not None and time.monotonic() - self.pi_last_rx < self.settings.live_timeout_s
        return StatusResponse(
            mode=mode, serial=SerialInfo(connected=self.serial.is_connected(), port=self.serial.port or None, baud_rate=self.serial.baud,
                                         last_telemetry_at=self.serial.last_rx_at, error=self.serial.error,
                                         messages_ok=self.serial.ok_count, messages_ignored=self.serial.ignored_count),
            raspberry_pi=RaspberryPiInfo(enabled=self.settings.raspberry_pi_mode, connected=pi_live,
                                         last_telemetry_at=self.pi_last_rx_at, messages_ok=self.pi_messages_ok,
                                         person_count=self.pi_person_count, last_person_count_at=self.pi_person_count_at),
            controller="online" if live else "offline", sensors=sensors,
            model=ModelInfo(loaded=self.vision.model_loaded, path=str(self.vision.model_path), error=self.vision.model_error),
            camera=CameraInfo(active=self.vision.camera_active, fps=round(self.vision.fps, 1), latency_ms=round(self.vision.latency_ms, 1)),
            battery=None if live or (self.settings.raspberry_pi_mode and self.pi_latest is not None) else round(self.sim.battery, 1),
            rover=RoverInfo(row=p.row, column=p.col, coordinate=coordinate(p.row, p.col), heading=HEADINGS[p.heading]),  # type: ignore[arg-type]
            goal=coordinate(*self.map.goal) if self.map.goal else None, movement=tel.movement if tel else "S",
            obstacle_detected=tel.obstacle_detected if tel else False, person_count=self.person_count(),
            temperature_c=tel.temperature_tenths / 10.0 if tel else None, humidity_pct=tel.humidity_tenths / 10.0 if tel else None,
            smoke_value=tel.smoke_value if tel else None, fire_risk_level=risk_level(max(tel.risk_score if tel else 0, cell_score)),
            route={**self.executor.status(), "emergencyStopLatched": self.emergency_stop_latched},
            data_source=tel.source if tel else "SIMULATED")

    def map_snapshot(self) -> MapSnapshot:
        meta = self.map.snapshot_meta()
        tel = self.telemetry()
        if not calibration_is_valid(self.settings.wheel_diameter_m, self.settings.wheel_track_m,
                                    self.settings.encoder_pulses_per_revolution, self.settings.map_cell_size_m):
            odometry_status = "calibration_missing"
        elif not tel or tel.left_encoder_count is None or tel.right_encoder_count is None:
            odometry_status = "encoder_data_unavailable"
        elif not meta["odometry_available"]:
            odometry_status = "collecting_encoder_motion"
        else:
            odometry_status = "available"
        return MapSnapshot(cells=self.map.cells(self.mode == "LIVE"), odometry_status=odometry_status, **meta)

    def person_status(self) -> PersonDetection:
        st = self.vision.status()
        if self.settings.raspberry_pi_mode:
            st.person_count = st.count = self.pi_person_count
            # The laptop cannot inspect the remote Pi process, camera or model.
            st.model_loaded = None
            st.model_path = "/home/pi/person_detection/models/firebird_person_yolov8n_best.onnx"
            st.model_error = None
            st.error = None
            st.camera_active = False  # Pi count is forwarded; its MJPEG stream is not part of this API.
        if not self.vision.camera_active and not self.settings.raspberry_pi_mode:
            st.person_count = st.count = self.person_count()
        return st


def ctx_of(obj: Any) -> Context:
    return obj.app.state.ctx


# ====================================================================== app
@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    logging.basicConfig(level=settings.log_level.upper(), format="%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    loop = asyncio.get_running_loop()
    ctx = Context(settings, loop)
    app.state.ctx = ctx
    if settings.raspberry_pi_mode:
        ctx.alerts.add("INFO", "SYSTEM", "Raspberry Pi network mode enabled. Laptop serial port is not opened.", "-", dedupe_s=0)
    elif settings.serial_port:
        ok, msg = await run_in_threadpool(ctx.serial.connect)
        ctx.alerts.add("INFO" if ok else "WARNING", "SYSTEM", msg if ok else f"{msg} Using SIMULATION MODE.", "-", dedupe_s=0)
    else:
        ctx.alerts.add("INFO", "SYSTEM", "No SERIAL_PORT configured. Starting in SIMULATION MODE.", "-", dedupe_s=0)
    if not settings.model_file.is_file():
        ctx.alerts.add("WARNING", "SYSTEM", "Model not found. Place trained .pt file in backend/models/.", "-", "Person detection is unavailable until then", dedupe_s=0)

    async def sim_loop() -> None:
        while True:
            try:
                ctx.check_mode()
                if ctx.mode == "SIMULATION" and ctx.sim.running:
                    tel = ctx.sim.step()
                    ctx.process_telemetry(tel, live=False)
                    ctx.emit("telemetry", tel)
                    await asyncio.sleep(ctx.sim.interval_s)
                else:
                    await asyncio.sleep(0.2)
            except Exception:  # noqa: BLE001
                logger.exception("simulation loop error")
                await asyncio.sleep(1)

    async def housekeeping_loop() -> None:
        while True:
            await asyncio.sleep(1.0)
            try:
                ctx.map.decay(1.0)
                ctx.map.set_health_risk(0.0 if ctx.mode == "LIVE" else (100.0 - ctx.sim.battery) / 200.0)
                ctx.emit("status", ctx.build_status())
                if ctx.vision.camera_active:
                    ctx.emit("person", ctx.person_status())
                if ctx.map.version != ctx._last_map_version and ctx.manager.count:
                    ctx._last_map_version = ctx.map.version
                    ctx.emit("map", ctx.map_snapshot())
                if ctx.executor.version != ctx._last_exec_version:
                    ctx._last_exec_version = ctx.executor.version
                    ctx.emit("route", ctx.executor.status())
            except Exception:  # noqa: BLE001
                logger.exception("housekeeping error")

    tasks = [asyncio.create_task(sim_loop()), asyncio.create_task(housekeeping_loop()), asyncio.create_task(ctx.executor.run())]
    logger.info("FireBird backend ready. Mode: %s. Docs: http://localhost:%d/docs", ctx.mode, settings.port)
    try:
        yield
    finally:
        for t in tasks:
            t.cancel()
        await run_in_threadpool(ctx.vision.stop)
        await run_in_threadpool(ctx.serial.disconnect)
        logger.info("Shutdown complete")


app = FastAPI(title="FireBird PC backend", version="1.0.0", lifespan=lifespan)
_origins = get_settings().cors_list
app.add_middleware(CORSMiddleware, allow_origins=sorted(set(_origins + [o.replace("localhost", "127.0.0.1") for o in _origins])),
                   allow_methods=["*"], allow_headers=["*"])


@app.exception_handler(Exception)
async def unhandled(_: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled error")
    return JSONResponse(status_code=500, content={"detail": f"Internal error: {exc}"})


# ---------------------------------------------------------------- health / status / telemetry
@app.get("/api/health")
async def health(request: Request) -> dict:
    c = ctx_of(request)
    tel = c.telemetry()
    status_data = c.build_status()
    return {"status": "ok", "mode": c.mode, "serial": jsonable_encoder(status_data.serial, by_alias=True),
            "raspberryPi": jsonable_encoder(status_data.raspberry_pi, by_alias=True),
            "simulation": {"running": c.sim.running, "speed": c.sim.speed, "tick": c.sim.tick},
            "camera": {"active": c.vision.camera_active, "fps": round(c.vision.fps, 1), "error": c.vision.error},
            "model": {"loaded": c.vision.model_loaded, "path": str(c.vision.model_path), "error": c.vision.model_error},
            "planner": "ready", "lastTelemetryTimestamp": tel.timestamp.isoformat() if tel else None,
            "dashboardClients": c.manager.count}


@app.get("/api/status", response_model=StatusResponse)
async def status(request: Request) -> StatusResponse:
    return ctx_of(request).build_status()


@app.get("/api/telemetry")
async def telemetry(request: Request) -> dict:
    c = ctx_of(request)
    tel = c.telemetry()
    return {"latest": jsonable_encoder(tel, by_alias=True) if tel else None, "mode": c.mode,
            "source": tel.source if tel else None,
            "raw": list(c.raw_log) if tel and tel.source in {"LIVE_PI", "LIVE_SERIAL"} else []}


@app.post("/api/raspberry-pi/telemetry")
async def raspberry_pi_telemetry(request: Request, body: dict = Body(...)) -> dict:
    """Receive one original FireBird wire frame forwarded by the Pi; parsing stays centralized."""
    c = ctx_of(request)
    if not c.settings.raspberry_pi_mode:
        raise HTTPException(status_code=409, detail="Enable RASPBERRY_PI_MODE to receive Raspberry Pi telemetry.")
    line = body.get("line")
    if not isinstance(line, str) or not line.strip():
        raise HTTPException(status_code=422, detail="Body must include the raw FireBird telemetry line as 'line'.")
    parsed = parse_telemetry(line)
    if parsed is None:
        raise HTTPException(status_code=422, detail="Invalid FireBird telemetry frame; expected the documented $FB format.")
    person_count = body.get("personCount")
    if person_count is not None:
        if isinstance(person_count, bool) or not isinstance(person_count, int) or person_count < 0:
            raise HTTPException(status_code=422, detail="personCount must be a non-negative integer.")
        parsed = parsed.model_copy(update={"person_count": person_count})
    parsed = parsed.model_copy(update={"source": "LIVE_PI", "timestamp": utcnow()})
    c.on_pi_telemetry(parsed, line.strip(), person_count)
    return {"accepted": True, "source": "LIVE_PI", "timestamp": parsed.timestamp.isoformat(),
            "messagesOk": c.pi_messages_ok}


@app.post("/api/raspberry-pi/person-count")
async def raspberry_pi_person_count(request: Request, body: dict = Body(...)) -> dict:
    """Accept the Pi YOLO count independently of sensor frame timing."""
    c = ctx_of(request)
    if not c.settings.raspberry_pi_mode:
        raise HTTPException(status_code=409, detail="Enable RASPBERRY_PI_MODE to receive Raspberry Pi data.")
    count = body.get("personCount")
    if isinstance(count, bool) or not isinstance(count, int) or count < 0:
        raise HTTPException(status_code=422, detail="personCount must be a non-negative integer.")
    c.on_pi_person_count(count)
    return {"accepted": True, "personCount": count, "timestamp": c.pi_person_count_at.isoformat()}


@app.get("/api/raspberry-pi/command/next")
async def raspberry_pi_command_next(request: Request, response: Response) -> dict:
    """One-time command claim for the Pi's existing serial owner."""
    c = ctx_of(request)
    if not c.settings.raspberry_pi_mode:
        raise HTTPException(status_code=409, detail="Enable RASPBERRY_PI_MODE to use the Pi command bridge.")
    age = None if c.pi_last_rx is None else time.monotonic() - c.pi_last_rx
    with c._pi_command_lock:
        stop_pending = bool(c._pi_pending_command and c._pi_pending_command["command"] == "MOVE:STOP")
    if (age is None or age >= c.settings.live_timeout_s) and not stop_pending:
        raise HTTPException(status_code=409, detail="Raspberry Pi telemetry is stale; no command is available.")
    response.headers["Cache-Control"] = "no-store"
    item = c.take_pi_command()
    return {"missionActive": c.executor.running, **(item or {})}


@app.post("/api/raspberry-pi/command/{command_id}/ack")
async def raspberry_pi_command_ack(command_id: int, request: Request, body: dict = Body(...)) -> dict:
    c = ctx_of(request)
    if not c.settings.raspberry_pi_mode:
        raise HTTPException(status_code=409, detail="Enable RASPBERRY_PI_MODE to acknowledge Pi commands.")
    accepted, error = body.get("accepted"), body.get("error")
    if not isinstance(accepted, bool) or (error is not None and not isinstance(error, str)):
        raise HTTPException(status_code=422, detail="Body requires boolean accepted and optional string error.")
    if not c.acknowledge_pi_command(command_id, accepted, error):
        raise HTTPException(status_code=409, detail="Unknown, duplicate or expired command acknowledgement.")
    return {"accepted": True, "commandId": command_id}


# ---------------------------------------------------------------- commands / serial / simulation
@app.post("/api/command")
async def command(body: CommandRequest, request: Request) -> dict:
    c = ctx_of(request)
    ok, msg = c.send_move(body.command, "api")
    if not ok:
        raise HTTPException(status_code=409, detail=msg)
    return {"success": True, "message": msg, "command": body.command, "mode": c.mode, "sent": body.command,
            "state": jsonable_encoder(c.build_status(), by_alias=True)}


@app.post("/api/serial/connect")
async def serial_connect(request: Request, body: Optional[SerialConnectRequest] = None) -> dict:
    c = ctx_of(request)
    if c.settings.raspberry_pi_mode:
        raise HTTPException(status_code=409, detail="Laptop serial connection is disabled in Raspberry Pi network mode.")
    ok, msg = await run_in_threadpool(c.serial.connect, body.port if body else None, body.baud_rate if body else None)
    c.alerts.add("INFO" if ok else "WARNING", "SYSTEM", msg, "-", dedupe_s=0)
    if not ok:
        raise HTTPException(status_code=409, detail=msg)
    return {"success": True, "message": msg, "mode": c.mode}


@app.post("/api/serial/disconnect")
async def serial_disconnect(request: Request) -> dict:
    c = ctx_of(request)
    await run_in_threadpool(c.serial.disconnect)
    c.live_latest = None
    c.check_mode()
    c.alerts.add("INFO", "SYSTEM", "Serial disconnected by user", "-", dedupe_s=0)
    return {"success": True, "mode": c.mode}


@app.post("/api/serial/autonomous")
async def serial_autonomous(request: Request) -> dict:
    """Send C:A to return movement control to FireBird's onboard avoidance."""
    c = ctx_of(request)
    if c.settings.raspberry_pi_mode:
        raise HTTPException(status_code=409, detail="Laptop serial commands are disabled in Raspberry Pi telemetry-only mode.")
    reason = c.navigation_block_reason(check_start=False)
    if reason:
        raise HTTPException(status_code=409, detail=reason)
    if c.executor.running:
        c.executor.stop("Route stopped; returned control to FireBird autonomous avoidance")
    if not c.serial.send_autonomous():
        raise HTTPException(status_code=409, detail="Could not send autonomous mode command to FireBird.")
    return {"success": True, "message": "C:A sent; FireBird autonomous avoidance resumed."}


@app.get("/api/simulation")
async def simulation_state(request: Request) -> dict:
    c = ctx_of(request)
    return {"running": c.sim.running, "speed": c.sim.speed, "tick": c.sim.tick, "battery": round(c.sim.battery, 1), "mode": c.mode,
            "note": "The simulator only generates telemetry while mode is SIMULATION."}


@app.post("/api/simulation")
async def simulation_control(body: SimulationControl, request: Request) -> dict:
    c = ctx_of(request)
    if body.speed is not None:
        c.sim.set_speed(body.speed)
    if body.action == "pause":
        c.sim.pause()
    elif body.action == "start":
        c.sim.resume()
    elif body.action == "reset":
        c.executor.stop("Simulation reset")
        c.sim.reset()
    return await simulation_state(request)


# ---------------------------------------------------------------- map / route
def _cell(ref: Any) -> tuple[int, int]:
    try:
        return parse_coordinate(ref) if isinstance(ref, str) else (ref.row, ref.column)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/map", response_model=MapSnapshot)
async def get_map(request: Request) -> MapSnapshot:
    return ctx_of(request).map_snapshot()


@app.post("/api/map/resize")
async def resize_map(body: ResizeRequest, request: Request) -> dict:
    c = ctx_of(request)
    c.executor.stop("Map resized")
    c.map.resize(body.rows, body.columns)
    return c.map.snapshot_meta()


@app.post("/api/map/clear")
async def clear_map(request: Request) -> dict:
    c = ctx_of(request)
    c.map.clear()
    c.after_person_change(c.person_count())
    return c.map.snapshot_meta()


@app.post("/api/map/cell")
async def update_cell(body: CellUpdate, request: Request) -> dict:
    """Edit one cell with `action`, or sync the is_obstacle / is_person / is_fire flags sent by the dashboard."""
    c = ctx_of(request)
    try:
        actions: list[str] = []
        if body.action:
            actions.append(body.action)
        else:
            cell = c.map.get_cell(body.row, body.column, c.mode == "LIVE")
            for flag, now, add, rem in ((body.is_obstacle, cell.is_obstacle, "ADD_OBSTACLE", "REMOVE_OBSTACLE"),
                                        (body.is_person, cell.is_person, "ADD_PERSON", "REMOVE_PERSON"),
                                        (body.is_fire, cell.is_fire, "ADD_HOTSPOT", "REMOVE_HOTSPOT")):
                if flag is not None and flag != now:
                    actions.append(add if flag else rem)
        for a in actions:
            c.map.apply_action(body.row, body.column, a)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    c.after_person_change(c.person_count())
    if c.executor.running and any(a in ("ADD_OBSTACLE", "ADD_HOTSPOT", "ADD_PERSON") for a in actions):
        c.executor.replan()  # incremental replanning when the map changes
    cell = c.map.get_cell(body.row, body.column, c.mode == "LIVE")
    return {"success": True, "applied": actions, "cell": jsonable_encoder(cell, by_alias=True)}


@app.post("/api/map/route", response_model=PlannedRoute)
async def map_route(body: RouteRequest, request: Request) -> PlannedRoute:
    """Plan a route (RAIR-inspired A* or standard A*). Sends nothing to FireBird unless send_route is true."""
    c = ctx_of(request)
    if c.executor.running:
        c.executor.stop("Navigation stopped because a new route was requested")
    if c.executor.state == "STOPPING":
        until = time.monotonic() + 3.0
        while c.executor.state == "STOPPING" and time.monotonic() < until:
            await asyncio.sleep(0.05)
    if c.executor.state == "FAILED":
        raise HTTPException(status_code=409, detail="Navigation stop was not confirmed. Use Emergency Stop and verify the rover before selecting another destination.")
    if not c.executor.reset_for_route():
        raise HTTPException(status_code=409, detail="Navigation is in a failed stop state. Restore communication and verify the rover is stopped before planning another route.")
    same = not (body.rows and body.columns and (body.rows, body.columns) != (c.map.rows, c.map.cols))
    base = c.map if same else RiskMap(c.settings, body.rows, body.columns)
    pose = c.map.pose
    if body.start:
        start = _cell(body.start)
    elif body.start_row is not None and body.start_column is not None:
        start = (body.start_row, body.start_column)
    else:
        start = (pose.row, pose.col)
    if body.goal:
        goal = _cell(body.goal)
    elif body.goal_row is not None and body.goal_column is not None:
        goal = (body.goal_row, body.goal_column)
    elif same and c.map.goal:
        goal = c.map.goal
    else:
        # Destination selection is intentionally a later dashboard phase. A missing
        # destination is a normal planner state, not a malformed request.
        return PlannedRoute(found=False, alpha=body.risk_attitude_alpha,
                            message="Select a destination to generate a route.",
                            explanation="No destination has been selected.", planner="rair-astar")
    for name, cell in (("start", start), ("goal", goal)):
        if not base.in_bounds(*cell):
            raise HTTPException(status_code=400, detail=f"The {name} cell is outside the {base.rows} x {base.cols} map.")
    ov = Overlay()
    for ref in body.obstacles:
        r, k = _cell(ref)
        if base.in_bounds(r, k) and (r, k) != start:
            ov.obstacles.add((r, k))
    for ref in body.persons:
        r, k = _cell(ref)
        if base.in_bounds(r, k):
            ov.persons.append((r, k))
    for hz in body.hazards:
        r, k = _cell(hz.coordinate) if hz.coordinate else (hz.row, hz.column)  # type: ignore[arg-type]
        if r is None or k is None or not base.in_bounds(r, k):
            raise HTTPException(status_code=400, detail="A hazard has an invalid cell.")
        ov.hazards.append((r, k, hz.risk_score / 100.0, hz.fire))
    if body.risk_values is not None:
        arr = np.array(body.risk_values, dtype=float)
        if arr.shape != (base.rows, base.cols):
            raise HTTPException(status_code=400, detail=f"riskValues must be {base.rows} x {base.cols}.")
        ov.floor = arr
    heading = heading_index(body.heading, pose.heading if start == (pose.row, pose.col) else 0)
    route = plan_route(base.cost_grid(ov), start, goal, heading, body.risk_attitude_alpha, body.risk_aware, c.settings.risk_cost_scale)
    if not route.found:
        c.alerts.add("WARNING", "PATH", "No safe route found.", coordinate(*goal), "Change goal or remove blocked cells", dedupe_s=3)
    if same:
        c.map.set_goal(*goal)
        c.last_route, c.last_goal = (route, goal) if route.found else (None, None)
    if body.send_route and route.found:
        if not same:
            raise HTTPException(status_code=400, detail="Cannot send a route planned on a different grid size than the backend map.")
        reason = c.navigation_block_reason(check_start=True)
        if reason:
            raise HTTPException(status_code=409, detail=reason)
        c.executor.start(route, goal, body.risk_attitude_alpha, body.risk_aware)
        route.route_sent = True
    return route


@app.get("/api/route")
async def route_status(request: Request) -> dict:
    c = ctx_of(request)
    return {"executor": c.executor.status(), "lastRoute": jsonable_encoder(c.last_route, by_alias=True) if c.last_route else None}


@app.post("/api/route/{action}")
async def route_control(action: str, request: Request) -> dict:
    c = ctx_of(request)
    if action == "start":
        if c.executor.state == "FAILED":
            raise HTTPException(status_code=409, detail="Navigation is locked after a failed stop. Use Emergency Stop and verify the rover before restarting.")
        if not c.last_route or not c.last_goal:
            raise HTTPException(status_code=409, detail="No planned route. Call POST /api/map/route first.")
        reason = c.navigation_block_reason(check_start=True)
        if reason:
            raise HTTPException(status_code=409, detail=reason)
        try:
            route_start = parse_coordinate(c.last_route.cells[0]) if c.last_route.cells else None
        except ValueError:
            route_start = None
        if route_start != (c.map.pose.row, c.map.pose.col):
            raise HTTPException(status_code=409, detail="Rover position changed since route planning. Recalculate the route before starting navigation.")
        c.executor.start(c.last_route, c.last_goal, c.last_route.alpha, c.last_route.planner != "astar")
    elif action == "pause":
        c.executor.pause("paused by user")
    elif action == "resume":
        reason = c.navigation_block_reason(check_start=True)
        if reason:
            raise HTTPException(status_code=409, detail=reason)
        if not c.executor.resume():
            raise HTTPException(status_code=409, detail="No paused route to resume.")
    elif action == "stop":
        c.executor.stop("Route stopped by user")
    else:
        raise HTTPException(status_code=404, detail="Use start, pause, resume or stop.")
    return {"success": True, "executor": c.executor.status()}


@app.post("/api/navigation/emergency-stop")
async def navigation_emergency_stop(request: Request) -> dict:
    """Send the existing MOVE:STOP through the configured single serial owner."""
    c = ctx_of(request)
    c.emergency_stop_latched = True
    if c.executor.running:
        c.executor.stop("Emergency stop requested from dashboard")
        if c.executor.state == "FAILED":
            raise HTTPException(status_code=409, detail="STOP could not be dispatched; verify the rover locally.")
        return {"success": True, "executor": c.executor.status(), "message": "STOP sent or queued through the existing command path."}
    if c.settings.raspberry_pi_mode:
        ok, message = c.send_move("MOVE:STOP", "api")
        if ok and message.startswith("PI_QUEUE:"):
            try:
                c._pi_failure_recovery_command_id = int(message.partition(":")[2])
            except ValueError:
                c._pi_failure_recovery_command_id = None
    elif c.serial.is_connected():
        ok = c.serial.send_command("MOVE:STOP")
        message = "STOP sent through the existing laptop serial manager." if ok else "Serial STOP write failed."
        if ok:
            c.tracker.note_sent("MOVE:STOP", apply_pose=False)
    else:
        ok, message = False, "FireBird serial connection is unavailable; STOP could not be sent."
    if not ok:
        raise HTTPException(status_code=409, detail=message)
    if c.executor.state == "FAILED" and not c.settings.raspberry_pi_mode:
        tel = c.live_latest
        age = c.serial.seconds_since_rx()
        if tel and tel.movement == "S" and age is not None and age < min(c.settings.live_timeout_s, 1.5):
            c.executor.clear_failed_after_stop()
    return {"success": True, "executor": c.executor.status(), "message": message}


@app.post("/api/navigation/reset-emergency-stop")
async def navigation_reset_emergency_stop(request: Request) -> dict:
    c = ctx_of(request)
    if c.settings.raspberry_pi_mode:
        tel, age = c.pi_latest, None if c.pi_last_rx is None else time.monotonic() - c.pi_last_rx
    else:
        tel, age = c.live_latest, c.serial.seconds_since_rx()
    if (c.mode != "LIVE" or tel is None or age is None or age >= min(c.settings.live_timeout_s, 1.5)
            or tel.movement != "S" or tel.obstacle_detected or tel.risk_score >= 75 or tel.flags & 0x07
            or tel.dht_ok is not True or tel.smoke_value <= 0
            or tel.temperature_tenths / 10.0 >= 55 or tel.smoke_value >= c.settings.smoke_high
            or c.map.sample(c.map.pose.row, c.map.pose.col)["score"] >= 75
            or (c.person_count() > 0 and c.vision.safety_action == "stop")):
        raise HTTPException(status_code=409, detail="Cannot reset emergency stop until fresh telemetry confirms stopped motion and safe conditions.")
    c.emergency_stop_latched = False
    c.executor.clear_failed_after_stop()
    return {"success": True, "emergencyStopLatched": False, "executor": c.executor.status()}


# ---------------------------------------------------------------- alerts
@app.get("/api/alerts")
async def get_alerts(request: Request, severity: Optional[str] = None, module: Optional[str] = None, acknowledged: Optional[bool] = None) -> list:
    return jsonable_encoder(ctx_of(request).alerts.list(severity, module, acknowledged), by_alias=True)


@app.post("/api/alerts/acknowledge")
async def ack_alerts(body: AckRequest, request: Request) -> dict:
    a = ctx_of(request).alerts
    if body.ids == "all":
        n = a.acknowledge(None)
    else:
        ids = ([body.id] if body.id is not None else []) + (body.ids or [])  # type: ignore[operator]
        if not ids:
            raise HTTPException(status_code=400, detail="Send an alert id or ids.")
        n = a.acknowledge(ids)
    return {"success": True, "acknowledged": n}


@app.post("/api/alerts/clear-noncritical")
async def clear_alerts(request: Request) -> dict:
    return {"success": True, "cleared": ctx_of(request).alerts.clear_noncritical()}


# ---------------------------------------------------------------- person detection
@app.get("/api/person/status", response_model=PersonDetection)
async def person_status(request: Request) -> PersonDetection:
    return ctx_of(request).person_status()


@app.post("/api/person/start", response_model=PersonDetection)
async def person_start(request: Request, body: Optional[PersonStartRequest] = None) -> PersonDetection:
    c = ctx_of(request)
    if body:
        if body.confidence_threshold is not None:
            c.vision.threshold = body.confidence_threshold
        if body.send_to_fire_bird is not None:
            c.vision.send_to_firebird = body.send_to_fire_bird
    ok, msg = await run_in_threadpool(c.vision.start)
    if not ok:
        c.alerts.add("WARNING", "SYSTEM", msg, "-", "Check the model file and camera", dedupe_s=10)
        raise HTTPException(status_code=409, detail=msg)
    return c.person_status()


@app.post("/api/person/stop", response_model=PersonDetection)
async def person_stop(request: Request) -> PersonDetection:
    c = ctx_of(request)
    await run_in_threadpool(c.vision.stop)
    c.after_person_change(c.person_count())
    return c.person_status()


@app.post("/api/person/safety-action")
async def person_safety(body: SafetyActionRequest, request: Request) -> dict:
    c = ctx_of(request)
    c.vision.safety_action = body.action
    c.after_person_change(c.person_count())
    return {"success": True, "action": body.action}


@app.get("/api/person/frame")
async def person_frame(request: Request) -> dict:
    """One camera frame as base64 JPEG (without boxes) plus the detections."""
    c = ctx_of(request)
    return {"jpegBase64": c.vision.frame_base64(), "status": jsonable_encoder(c.person_status(), by_alias=True)}


@app.get("/api/person/stream")
async def person_stream(request: Request, annotated: bool = False) -> StreamingResponse:
    """MJPEG stream. Plain frames by default (the dashboard draws the boxes); ?annotated=true draws boxes on the server."""
    c = ctx_of(request)
    if not c.vision.camera_active:
        raise HTTPException(status_code=409, detail="Camera is not running. Call POST /api/person/start first.")

    async def gen():
        while c.vision.camera_active:
            jpg = c.vision.frame_jpeg(annotated)
            if jpg:
                yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + jpg + b"\r\n"
            await asyncio.sleep(0.05)
    return StreamingResponse(gen(), media_type="multipart/x-mixed-replace; boundary=frame")


# ---------------------------------------------------------------- websocket
@app.websocket("/ws/dashboard")
async def dashboard_ws(ws: WebSocket) -> None:
    c = ctx_of(ws)
    await c.manager.connect(ws)
    try:
        tel = c.telemetry()
        await ws.send_json({"type": "status", "data": jsonable_encoder(c.build_status(), by_alias=True)})
        if tel:
            await ws.send_json({"type": "telemetry", "data": jsonable_encoder(tel, by_alias=True)})
        await ws.send_json({"type": "map", "data": jsonable_encoder(c.map_snapshot(), by_alias=True)})
        await ws.send_json({"type": "person", "data": jsonable_encoder(c.person_status(), by_alias=True)})
        for a in reversed(c.alerts.list()[:20]):
            await ws.send_json({"type": "alert", "data": jsonable_encoder(a, by_alias=True)})
        while True:
            text = await ws.receive_text()  # keeps the connection open; also notices disconnects
            if text == "ping":
                await ws.send_json({"type": "pong"})
    except WebSocketDisconnect:
        pass
    except Exception:  # noqa: BLE001
        logger.debug("WebSocket closed with error", exc_info=True)
    finally:
        await c.manager.disconnect(ws)


if __name__ == "__main__":
    s = get_settings()
    uvicorn.run(app, host=s.host, port=s.port, log_level=s.log_level.lower())
