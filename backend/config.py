"""Configuration loaded from environment variables and an optional .env file."""
from __future__ import annotations

import sys
from functools import lru_cache
from pathlib import Path

from pydantic import Field, ValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent


class Settings(BaseSettings):
    """All settings can be overridden by environment variables (names are case-insensitive)."""

    model_config = SettingsConfigDict(env_file=str(BASE_DIR / ".env"), env_file_encoding="utf-8", extra="ignore")

    # --- core settings (see config.example.env) ---
    serial_port: str = "COM3"
    baud_rate: int = Field(9600, ge=1200, le=921600)
    raspberry_pi_mode: bool = False
    model_path: str = "models/firebird_person_yolov8n_best.pt"
    camera_index: int = Field(0, ge=0, le=20)
    confidence_threshold: float = Field(0.60, ge=0.30, le=0.90)
    person_count_stable_frames: int = Field(3, ge=1, le=30)
    simulation_tick_ms: int = Field(200, ge=50, le=2000)
    map_rows: int = Field(10, ge=5, le=20)
    map_columns: int = Field(10, ge=5, le=20)
    # Leave unset until measured from the actual rover and encoder.
    # FireBird V measured odometry calibration
    wheel_diameter_m: float | None = Field(0.05, gt=0)
    wheel_track_m: float | None = Field(0.155, gt=0)
    # Leave unset until measured for the installed encoder.
    encoder_pulses_per_revolution: int | None = Field(None, gt=0)
    map_cell_size_m: float | None = Field(None, gt=0)
    cors_origins: str = "http://localhost:5173,http://localhost:3000"

    # --- planner weights (risk(n) = weighted sum of components, each 0..1) ---
    w_obs: float = Field(0.35, ge=0, le=1)
    w_person: float = Field(0.25, ge=0, le=1)
    w_thermal: float = Field(0.20, ge=0, le=1)
    w_smoke: float = Field(0.15, ge=0, le=1)
    w_health: float = Field(0.05, ge=0, le=1)
    risk_cost_scale: float = Field(40.0, gt=0, le=1000)  # extra moves per 1.0 of risk at alpha = 1

    # --- risk map tuning ---
    risk_spread_k_obstacle: float = Field(1.6, gt=0)  # neighbor_risk = source_risk * exp(-k * distance)
    risk_spread_k_thermal: float = Field(0.7, gt=0)
    risk_spread_k_smoke: float = Field(0.5, gt=0)
    risk_spread_k_person: float = Field(0.9, gt=0)
    risk_decay_per_s: float = Field(0.05, ge=0)
    smoke_baseline: int = Field(150, ge=0)  # raw smoke ADC value in clean air (calibrate!)
    smoke_high: int = Field(600, ge=1)  # raw value treated as very high smoke (calibrate!)
    live_timeout_s: float = Field(3.0, gt=0)  # no telemetry for this long => back to simulation
    host: str = "0.0.0.0"
    port: int = Field(8000, ge=1, le=65535)
    log_level: str = "INFO"

    @field_validator("serial_port")
    @classmethod
    def _port(cls, v: str) -> str:
        v = v.strip()
        return "" if v.upper() in {"NONE", "SIM", "SIMULATION"} else v

    @property
    def cors_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def model_file(self) -> Path:
        p = Path(self.model_path)
        return p if p.is_absolute() else BASE_DIR / p


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Load settings once. Prints a clear message and exits if a value is invalid."""
    try:
        return Settings()
    except ValidationError as e:
        lines = ["Invalid configuration:"]
        for err in e.errors():
            lines.append(f"  - {'.'.join(str(x) for x in err['loc']).upper()}: {err['msg']}")
        lines.append("Fix your .env file (see config.example.env) and start again.")
        print("\n".join(lines), file=sys.stderr)
        raise SystemExit(2)
