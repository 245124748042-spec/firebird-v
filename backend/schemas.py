"""Pydantic models. JSON uses camelCase (for the React dashboard); snake_case is also accepted on input."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal, Optional, Union

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, computed_field
from pydantic.alias_generators import to_camel

Movement = Literal["F", "B", "L", "R", "S"]
DataSource = Literal["SIMULATED", "LIVE_SERIAL", "LIVE_PI"]
RiskLevel = Literal["SAFE", "CAUTION", "WARNING", "CRITICAL"]
Severity = Literal["INFO", "WARNING", "CRITICAL"]
AlertModule = Literal["OBSTACLE", "PERSON", "PATH", "ENVIRONMENT", "SYSTEM"]
MoveCommand = Literal["MOVE:FORWARD", "MOVE:BACKWARD", "MOVE:LEFT", "MOVE:RIGHT", "MOVE:STOP"]
CellAction = Literal["ADD_OBSTACLE", "REMOVE_OBSTACLE", "ADD_PERSON", "REMOVE_PERSON", "ADD_HOTSPOT", "REMOVE_HOTSPOT", "CLEAR_CELL"]


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class CamelModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


# ------------------------------------------------------------------ telemetry
class Telemetry(CamelModel):
    """One FireBird telemetry sample. `source` says whether it is real serial data or simulated."""
    left_ir: int
    center_ir: int
    right_ir: int
    side_ir: int
    temperature_tenths: int
    humidity_tenths: int
    smoke_value: int
    obstacle_detected: bool
    movement: Movement
    risk_score: int = Field(ge=0, le=100)
    person_count: int = Field(ge=0)
    # Current FireBird V protocol fields; optional for simulator/legacy frames.
    ir5: Optional[int] = None
    robot_ms: Optional[int] = None
    env_risk: Optional[int] = None
    total_risk: Optional[int] = None
    speed: Optional[int] = None
    dht_ok: Optional[bool] = None
    flags: int = 0
    left_encoder_count: Optional[int] = None
    right_encoder_count: Optional[int] = None
    timestamp: datetime = Field(default_factory=utcnow)
    source: DataSource


# ------------------------------------------------------------------ map
class MapCell(CamelModel):
    row: int
    column: int
    coordinate: str
    is_obstacle: bool
    is_person: bool
    is_fire: bool
    temperature: Optional[float] = None
    smoke: Optional[float] = None
    risk_score: float
    risk_level: RiskLevel
    last_updated: datetime


class CellIndex(CamelModel):
    row: int
    column: int


CellRef = Union[str, CellIndex]


class HazardIn(CamelModel):
    coordinate: Optional[str] = None
    row: Optional[int] = None
    column: Optional[int] = None
    risk_score: float = Field(75, ge=0, le=100)
    fire: bool = False


class RouteRequest(CamelModel):
    """Either start_row/start_column or start ("J1") may be used; same for the goal."""
    start_row: Optional[int] = None
    start_column: Optional[int] = None
    goal_row: Optional[int] = None
    goal_column: Optional[int] = None
    start: Optional[str] = None
    goal: Optional[str] = None
    rows: Optional[int] = None
    columns: Optional[int] = None
    heading: Optional[Literal["N", "E", "S", "W"]] = None
    obstacles: list[CellRef] = Field(default_factory=list)
    persons: list[CellRef] = Field(default_factory=list)
    hazards: list[HazardIn] = Field(default_factory=list)
    risk_values: Optional[list[list[float]]] = None
    risk_attitude_alpha: float = Field(1.5, ge=0.5, le=5.0, validation_alias=AliasChoices("risk_attitude_alpha", "riskAttitudeAlpha", "alpha"))
    risk_aware: bool = True
    send_route: bool = False


class PlannedRoute(CamelModel):
    found: bool
    cells: list[str] = Field(default_factory=list)
    commands: list[str] = Field(default_factory=list)
    total_cost: float = 0.0
    total_risk: float = 0.0
    alpha: float = 1.5
    message: str = ""
    shortest_cells: list[str] = Field(default_factory=list)
    shortest_length: int = 0
    shortest_risk: float = 0.0
    extra_moves: int = 0
    explanation: str = ""
    planner: str = "rair-astar"
    route_sent: bool = False


class CellUpdate(CamelModel):
    """Edit a cell with `action`. For dashboard sync you may instead send the is_* flags."""
    row: int
    column: int
    action: Optional[CellAction] = None
    is_obstacle: Optional[bool] = None
    is_person: Optional[bool] = None
    is_fire: Optional[bool] = None


class MapSnapshot(CamelModel):
    rows: int
    columns: int
    version: int
    rover: dict
    goal: Optional[str] = None
    cells: list[MapCell]
    odometry_path: list[dict[str, float]] = Field(default_factory=list)
    odometry_available: bool = False
    odometry_heading_rad: Optional[float] = None
    odometry_status: str = "unavailable"


class ResizeRequest(CamelModel):
    rows: int = Field(ge=5, le=20)
    columns: int = Field(ge=5, le=20)


# ------------------------------------------------------------------ commands / simulation
class CommandRequest(CamelModel):
    command: MoveCommand


class SimulationControl(CamelModel):
    action: Optional[Literal["start", "pause", "reset"]] = None
    speed: Optional[Literal[0.5, 1.0, 2.0]] = None


class SerialConnectRequest(CamelModel):
    port: Optional[str] = None
    baud_rate: Optional[int] = Field(None, ge=1200, le=921600)


# ------------------------------------------------------------------ person detection
class Detection(CamelModel):
    label: str = "person"
    confidence: float
    box: list[float] = Field(description="normalized [x, y, width, height], 0..1")
    box_px: list[int] = Field(description="[x1, y1, x2, y2] in pixels")


class PersonDetection(CamelModel):
    person_count: Optional[int] = None
    detections: list[Detection] = Field(default_factory=list)
    confidence_threshold: float = 0.6
    camera_active: bool = False
    model_loaded: Optional[bool] = None
    model_path: Optional[str] = None
    fps: float = 0.0
    inference_latency_ms: float = 0.0
    serial_message: Optional[str] = None
    # extra fields used by the dashboard
    count: Optional[int] = None
    latency_ms: float = 0.0
    last_serial_message: Optional[str] = None
    model_error: Optional[str] = None
    error: Optional[str] = None
    send_to_fire_bird: bool = Field(True, serialization_alias="sendToFireBird", validation_alias=AliasChoices("send_to_fire_bird", "sendToFireBird"))
    safety_action: Literal["ignore", "slow", "stop"] = "stop"


class PersonStartRequest(CamelModel):
    confidence_threshold: Optional[float] = Field(None, ge=0.30, le=0.90)
    send_to_fire_bird: Optional[bool] = Field(None, validation_alias=AliasChoices("send_to_fire_bird", "sendToFireBird"))


class SafetyActionRequest(CamelModel):
    action: Literal["ignore", "slow", "stop"]


# ------------------------------------------------------------------ alerts
class Alert(CamelModel):
    id: int
    timestamp: datetime
    severity: Severity
    module: AlertModule
    event: str
    grid_location: str = "-"
    recommended_action: str = "None"
    acknowledged: bool = False

    @computed_field  # type: ignore[prop-decorator]
    @property
    def status(self) -> Literal["Open", "Acknowledged"]:
        return "Acknowledged" if self.acknowledged else "Open"


class AckRequest(CamelModel):
    id: Optional[int] = None
    ids: Optional[Union[list[int], Literal["all"]]] = None


# ------------------------------------------------------------------ status / health
class SerialInfo(CamelModel):
    connected: bool
    port: Optional[str] = None
    baud_rate: Optional[int] = None
    last_telemetry_at: Optional[datetime] = None
    error: Optional[str] = None
    messages_ok: int = 0
    messages_ignored: int = 0


class SensorHealth(CamelModel):
    dht22: Literal["ok", "error", "unknown"] = "unknown"
    smoke: Literal["ok", "error", "unknown"] = "unknown"


class ModelInfo(CamelModel):
    loaded: bool
    path: Optional[str] = None
    error: Optional[str] = None


class CameraInfo(CamelModel):
    active: bool
    fps: float = 0.0
    latency_ms: float = 0.0


class RoverInfo(CamelModel):
    row: int
    column: int
    coordinate: str
    heading: Literal["N", "E", "S", "W"]


class RaspberryPiInfo(CamelModel):
    enabled: bool = False
    connected: bool = False
    last_telemetry_at: Optional[datetime] = None
    messages_ok: int = 0
    person_count: Optional[int] = None
    last_person_count_at: Optional[datetime] = None


class StatusResponse(CamelModel):
    mode: Literal["SIMULATION", "LIVE"]
    service: str = "ok"
    serial: SerialInfo
    raspberry_pi: RaspberryPiInfo = Field(default_factory=RaspberryPiInfo)
    controller: Literal["online", "offline"]
    sensors: SensorHealth
    model: ModelInfo
    camera: CameraInfo
    planner: Literal["ready", "unavailable"] = "ready"
    battery: Optional[float] = None
    rover: RoverInfo
    goal: Optional[str] = None
    movement: Movement = "S"
    obstacle_detected: bool = False
    person_count: int = 0
    temperature_c: Optional[float] = None
    humidity_pct: Optional[float] = None
    smoke_value: Optional[int] = None
    fire_risk_level: RiskLevel = "SAFE"
    route: dict = Field(default_factory=dict)
    data_source: DataSource = "SIMULATED"
