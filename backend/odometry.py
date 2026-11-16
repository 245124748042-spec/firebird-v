"""Differential-drive integration for cumulative signed or unsigned encoders."""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Optional


@dataclass(frozen=True)
class OdometryPose:
    x_m: float
    y_m: float
    heading_rad: float


class DifferentialDriveOdometry:
    """Integrate cumulative counters in a world frame where +y is north.

    Negative counters use their signed direction directly. Legacy unsigned
    counters are direction-adjusted using the FireBird movement field.
    """

    _MOVEMENT_SIGNS = {"F": (1, 1), "B": (-1, -1), "L": (-1, 1), "R": (1, -1)}

    def __init__(self) -> None:
        self.previous: Optional[tuple[int, int]] = None
        self.pose: Optional[OdometryPose] = None

    def reset_baseline(self) -> None:
        """Require the next sample to establish a new zero-distance baseline."""
        self.previous = None
        self.pose = None


    def update(self, left: int, right: int, movement: str, *, wheel_diameter_m: float,
               wheel_track_m: float, pulses_per_revolution: int,
               initial_heading_rad: float) -> tuple[OdometryPose, bool, bool]:
        """Return (pose, initialized, project); first sample adds no distance."""
        if self.previous is None or self.pose is None:
            self.previous = (left, right)
            self.pose = OdometryPose(0.0, 0.0, initial_heading_rad % (2 * math.pi))
            return self.pose, True, True

        old_left, old_right = self.previous
        # Update the baseline even for a discontinuity, so the next sample can recover.
        self.previous = (left, right)
        raw_deltas = (left - old_left, right - old_right)
        if raw_deltas == (0, 0):
            # Repeated counters are stationary; don't add duplicate trail points.
            return self.pose, False, False

        expected = self._MOVEMENT_SIGNS.get(movement)
        signed_counters = any(v < 0 for v in (left, right, old_left, old_right))
        legacy_uint32_rollover = not signed_counters and any(
            old >= 0x80000000 and current < old and old - current > 0x80000000
            for current, old in ((left, old_left), (right, old_right))
        )
        # Signed counters can still be positive before crossing zero. A reverse
        # or turn delta matching the movement's wheel directions identifies that
        # representation; unsigned rollover remains handled by the legacy path.
        signed_directional_delta = bool(
            expected and not legacy_uint32_rollover and any(delta < 0 for delta in raw_deltas)
            and all(delta == 0 or (1 if delta > 0 else -1) == expected[i]
                    for i, delta in enumerate(raw_deltas))
        )
        signed_mode = signed_counters or signed_directional_delta

        if signed_mode:
            # Wrap signed int32 counters without converting a legitimate rollover
            # into a multi-billion-tick jump.
            left_ticks = _signed_delta(left, old_left)
            right_ticks = _signed_delta(right, old_right)
            sign_left = sign_right = 1  # deltas already carry wheel direction
            if any(current == 0 and old != 0
                   for current, old in ((left, old_left), (right, old_right))):
                return self.pose, False, False
            if expected and any(delta and (1 if delta > 0 else -1) != expected[i]
                                for i, delta in enumerate((left_ticks, right_ticks))):
                # A direction-inconsistent jump is usually a reset or an
                # out-of-order sample. Baseline has been updated, so recovery is
                # immediate on the following valid frame.
                return self.pose, False, False
        else:
            # Legacy unsigned counters only increase; modulo arithmetic preserves
            # compatibility with their uint32 rollover behavior.
            left_ticks = (left - old_left) & 0xFFFFFFFF
            right_ticks = (right - old_right) & 0xFFFFFFFF
            if left_ticks > 0x7FFFFFFF or right_ticks > 0x7FFFFFFF:
                return self.pose, False, False
            sign_left, sign_right = expected or (0, 0)

        metres_per_tick = math.pi * wheel_diameter_m / pulses_per_revolution
        dl = sign_left * left_ticks * metres_per_tick
        dr = sign_right * right_ticks * metres_per_tick
        distance = (dl + dr) / 2.0
        turn = (dr - dl) / wheel_track_m
        theta = self.pose.heading_rad

        if abs(turn) < 1e-9:
            dx = distance * math.cos(theta)
            dy = distance * math.sin(theta)
        else:
            next_theta = theta + turn
            dx = (distance / turn) * (math.sin(next_theta) - math.sin(theta))
            dy = (distance / turn) * (math.cos(theta) - math.cos(next_theta))

        self.pose = OdometryPose(self.pose.x_m + dx, self.pose.y_m + dy,
                                 (theta + turn) % (2 * math.pi))
        return self.pose, False, True


def _signed_delta(current: int, previous: int) -> int:
    """Return a signed int32 delta, including rollover at either endpoint."""
    delta = (current - previous) & 0xFFFFFFFF
    return delta - 0x100000000 if delta >= 0x80000000 else delta


def calibration_is_valid(wheel_diameter_m: Optional[float], wheel_track_m: Optional[float],
                         pulses_per_revolution: Optional[int], map_cell_size_m: Optional[float]) -> bool:
    values = (wheel_diameter_m, wheel_track_m, pulses_per_revolution, map_cell_size_m)
    return all(value is not None and math.isfinite(value) and value > 0 for value in values)


def command_pose_enabled(encoder_sample: bool, calibration_valid: bool) -> bool:
    """Keep legacy command dead-reckoning active until encoder odometry can run."""
    return not (encoder_sample and calibration_valid)


def map_heading_to_radians(heading_index: int) -> float:
    """Convert the map's N/E/S/W heading index to radians CCW from east."""
    return math.pi / 2 - (heading_index % 4) * math.pi / 2
