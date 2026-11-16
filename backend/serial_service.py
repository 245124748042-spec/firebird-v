"""Single-owner USB serial link for FireBird telemetry and safe high-level commands."""
from __future__ import annotations

import csv
import logging
import threading
import time
from datetime import datetime, timezone
from typing import Callable, Optional

import serial
from serial import SerialException

from schemas import Telemetry, utcnow

logger = logging.getLogger("firebird.serial")
COMMANDS = {"MOVE:FORWARD", "MOVE:BACKWARD", "MOVE:LEFT", "MOVE:RIGHT", "MOVE:STOP"}
WIRE_COMMANDS = {"MOVE:FORWARD": "C:F", "MOVE:BACKWARD": "C:B", "MOVE:LEFT": "C:L",
                 "MOVE:RIGHT": "C:R", "MOVE:STOP": "C:S"}
MOVES = {"F", "B", "L", "R", "S"}


def _timestamp(value: str):
    value = value.strip()
    if not value:
        return utcnow()
    try:
        # ISO timestamp, optionally ending in Z.
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        try:
            # Firmware millis/epoch values are kept as receive-time unless they
            # are clearly Unix seconds or milliseconds.
            n = float(value)
            if n > 1_000_000_000_000:
                return datetime.fromtimestamp(n / 1000.0, timezone.utc)
            if n > 1_000_000_000:
                return datetime.fromtimestamp(n, timezone.utc)
        except (ValueError, OverflowError, OSError):
            pass
        return utcnow()


def parse_telemetry(line: str) -> Optional[Telemetry]:
    """Parse legacy keyed frames or `$FB` CSV frames.

    Positional CSV order is `$FB,timestamp,L,C,R,S,T,H,SM[,OBS,MOVE,RISK,PC]`.
    Timestamp and trailing fields may be omitted. An optional CSV header is
    accepted; units for T/H are tenths of a degree/percent, matching the UI.
    """
    try:
        text = line.strip().lstrip("\ufeff")
        if not text:
            return None
        if text.upper().startswith("$FB"):
            text = text[3:].lstrip(" ,:")
            fields = next(csv.reader([text], skipinitialspace=True))
            fields = [x.strip() for x in fields]
            # Current FireBird V format: ms, IR1..IR5, temp_x10, hum_x10,
            # smoke, env_risk, total_risk, persons, dir, speed, dht_ok, flags.
            if len(fields) >= 16 and _is_number(fields[0]):
                ms = _int(fields[0])
                ir1, ir2, ir3, ir4, ir5 = map(_int, fields[1:6])
                temp, humidity, smoke, env_risk, total_risk = map(_int, fields[6:11])
                people = _int(fields[11])
                move = _movement(fields[12])
                speed = _int(fields[13])
                dht_ok = _bool(fields[14])
                flags = _int(fields[15])
                if (min(ir1, ir2, ir3, ir4, ir5, smoke, people, speed, flags) < 0
                        or not 0 <= env_risk <= 100 or not 0 <= total_risk <= 100 or move not in MOVES):
                    return None
                if len(fields) not in (16, 17, 19):
                    return None
                left_encoder = _counter(fields[17]) if len(fields) == 19 else None
                right_encoder = _counter(fields[18]) if len(fields) == 19 else None
                return Telemetry(left_ir=ir1, center_ir=ir2, right_ir=ir3, side_ir=ir4, ir5=ir5,
                                 temperature_tenths=temp, humidity_tenths=humidity, smoke_value=smoke,
                                 obstacle_detected=bool(flags & (1 << 3)), movement=move,
                                 risk_score=total_risk, person_count=people, timestamp=utcnow(),
                                 source="LIVE_SERIAL", robot_ms=ms, env_risk=env_risk,
                                 total_risk=total_risk, speed=speed, dht_ok=dht_ok, flags=flags,
                                 left_encoder_count=left_encoder, right_encoder_count=right_encoder)
            if fields and fields[0].lower() in {"timestamp", "ts", "millis", "ms"}:
                return None  # header, not a sample
            # Named CSV is useful when firmware includes a column header.
            names = {"timestamp", "ts", "l", "left", "left_ir", "t", "temp", "temperature"}
            if fields and fields[0].lower() in names and not _is_number(fields[0]):
                return None
            # An ISO timestamp is not numeric; distinguish it from sensor data.
            has_timestamp = len(fields) >= 8 and ("T" in fields[0] or "-" in fields[0] or _is_number(fields[0]))
            if has_timestamp:
                stamp, values = _timestamp(fields[0]), fields[1:]
            else:
                stamp, values = utcnow(), fields
            if len(values) < 7:
                return None
            # Required telemetry: L,C,R,S,T,H,SM. Optional OBS,MOVE,RISK,PC.
            left, center, right, side, temp, humidity, smoke = map(_int, values[:7])
            obs = _bool(values[7]) if len(values) > 7 and values[7] else False
            move = values[8].upper() if len(values) > 8 and values[8] else "S"
            risk = _int(values[9]) if len(values) > 9 and values[9] else 0
            people = _int(values[10]) if len(values) > 10 and values[10] else 0
            if move not in MOVES or not 0 <= risk <= 100 or people < 0:
                return None
            return Telemetry(left_ir=left, center_ir=center, right_ir=right, side_ir=side,
                             temperature_tenths=temp, humidity_tenths=humidity, smoke_value=smoke,
                             obstacle_detected=obs, movement=move, risk_score=risk, person_count=people,
                             timestamp=stamp, source="LIVE_SERIAL")

        # Existing firmware format remains supported: L:...,C:... etc.
        kv = dict(p.split(":", 1) for p in text.split(",") if ":" in p)
        required = {"L", "C", "R", "S", "T", "H", "SM", "OBS", "MOVE", "RISK", "PC"}
        if not required.issubset(kv):
            return None
        move, obs, risk, people = kv["MOVE"].upper(), _bool(kv["OBS"]), _int(kv["RISK"]), _int(kv["PC"])
        if move not in MOVES or not 0 <= risk <= 100 or people < 0:
            return None
        return Telemetry(left_ir=_int(kv["L"]), center_ir=_int(kv["C"]), right_ir=_int(kv["R"]),
                         side_ir=_int(kv["S"]), temperature_tenths=_int(kv["T"]), humidity_tenths=_int(kv["H"]),
                         smoke_value=_int(kv["SM"]), obstacle_detected=obs, movement=move, risk_score=risk,
                         person_count=people, timestamp=utcnow(), source="LIVE_SERIAL")
    except (ValueError, TypeError, csv.Error):
        return None


def _is_number(value: str) -> bool:
    try:
        float(value)
        return True
    except ValueError:
        return False


def _is_epoch(value: str) -> bool:
    return _is_number(value) and abs(float(value)) > 1_000_000_000


def _int(value: str) -> int:
    return int(float(value.strip()))


def _counter(value: str) -> int:
    """Parse signed or unsigned 32-bit cumulative AVR encoder counts."""
    n = int(value.strip())
    if not -0x80000000 <= n <= 0xFFFFFFFF:
        raise ValueError("encoder counter outside signed/unsigned 32-bit range")
    return n


def _bool(value: str) -> bool:
    v = value.strip().lower()
    if v in {"1", "true", "yes", "y", "obstacle"}:
        return True
    if v in {"0", "false", "no", "n", "clear"}:
        return False
    raise ValueError("invalid boolean field")


def _movement(value: str) -> str:
    v = value.strip().upper()
    return {"FORWARD": "F", "FWD": "F", "BACKWARD": "B", "BACK": "B",
            "LEFT": "L", "RIGHT": "R", "STOP": "S"}.get(v, v)


class SerialService:
    """Owns exactly one serial port and reader thread; connection is verified by telemetry."""

    def __init__(self, port: str, baud: int) -> None:
        self.port, self.baud = port, baud
        self._ser: Optional[serial.SerialBase] = None
        self._write_lock = threading.Lock()
        self._connect_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._stop = threading.Event()
        self._first_frame = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._latest: Optional[Telemetry] = None
        self.last_rx: Optional[float] = None
        self.last_rx_at = None
        self.error: Optional[str] = None
        self.ok_count = 0
        self.ignored_count = 0
        self.on_telemetry: Optional[Callable[[Telemetry, str], None]] = None
        self.on_disconnect: Optional[Callable[[str], None]] = None

    def is_connected(self) -> bool:
        return self._ser is not None and self._ser.is_open

    def connect(self, port: Optional[str] = None, baud: Optional[int] = None) -> tuple[bool, str]:
        with self._connect_lock:
            if self.is_connected() and self.seconds_since_rx() is not None and self.seconds_since_rx() < 3:
                return True, f"Already receiving FireBird telemetry on {self.port} at {self.baud} baud."
            self.disconnect(quiet=True)
            if port:
                self.port = port.strip()
            if baud:
                self.baud = baud
            if not self.port:
                self.error = "No serial port configured. Set SERIAL_PORT or provide a port in the connect request."
                return False, self.error
            try:
                ser = serial.serial_for_url(self.port, baudrate=self.baud, timeout=0.2, write_timeout=1)
            except (SerialException, OSError, ValueError) as e:
                self.error = f"Cannot open {self.port}: {e}. Check the COM port and close serial monitors."
                logger.warning(self.error)
                return False, self.error
            self._ser, self.error = ser, None
            self._stop.clear()
            self._first_frame.clear()
            self._thread = threading.Thread(target=self._reader, name="firebird-serial-reader", daemon=True)
            self._thread.start()
            logger.info("Serial port %s opened at %d baud; waiting for $FB telemetry", self.port, self.baud)
            if not self._first_frame.wait(timeout=5.0):
                detail = self.error or f"No valid $FB telemetry received on {self.port} at {self.baud} baud within 5 seconds. Check firmware baud rate and CSV format."
                self.error = detail
                self.disconnect(quiet=True)
                return False, detail
            return True, f"Verified FireBird telemetry on {self.port} at {self.baud} baud."

    def disconnect(self, quiet: bool = False) -> None:
        self._stop.set()
        t = self._thread
        if t and t.is_alive() and t is not threading.current_thread():
            t.join(timeout=1.5)
        self._close()
        with self._state_lock:
            self._latest = None
            self.last_rx = None
        if not quiet:
            logger.info("Serial disconnected")

    def _close(self) -> None:
        with self._write_lock:
            if self._ser is not None:
                try:
                    self._ser.close()
                except Exception:  # noqa: BLE001
                    pass
                self._ser = None

    def _reader(self) -> None:
        buf = b""
        while not self._stop.is_set():
            try:
                ser = self._ser
                if ser is None:
                    break
                chunk = ser.read(max(1, ser.in_waiting))
            except (SerialException, OSError, TypeError, AttributeError) as e:
                self.error = f"Serial connection lost: {e}"
                logger.warning(self.error)
                self._close()
                if self.on_disconnect:
                    self.on_disconnect(self.error)
                return
            if not chunk:
                continue
            buf += chunk
            if len(buf) > 4096:
                buf = b""
            while b"\n" in buf:
                raw, buf = buf.split(b"\n", 1)
                line = raw.decode("ascii", errors="ignore").strip()
                if not line:
                    continue
                tel = parse_telemetry(line)
                if tel is None:
                    self.ignored_count += 1
                    logger.debug("Ignored malformed/non-telemetry line: %r", line)
                    continue
                with self._state_lock:
                    self._latest, self.last_rx, self.last_rx_at = tel, time.monotonic(), tel.timestamp
                    self.ok_count += 1
                self._first_frame.set()
                if self.on_telemetry:
                    try:
                        self.on_telemetry(tel, line)
                    except Exception:  # noqa: BLE001
                        logger.exception("telemetry listener failed")

    def read_telemetry(self) -> Optional[Telemetry]:
        with self._state_lock:
            return self._latest

    def seconds_since_rx(self) -> Optional[float]:
        with self._state_lock:
            return None if self.last_rx is None else time.monotonic() - self.last_rx

    def _write(self, text: str) -> bool:
        with self._write_lock:
            if self._ser is None or not self._ser.is_open:
                return False
            try:
                self._ser.write((text.strip() + "\n").encode("ascii"))
                self._ser.flush()
                return True
            except (SerialException, OSError) as e:
                self.error = f"Write failed: {e}"
                logger.warning(self.error)
                return False

    def send_command(self, command: str) -> bool:
        if command not in COMMANDS:
            logger.error("Refused to send unsupported command %r", command)
            return False
        return self._write(WIRE_COMMANDS[command])

    def send_autonomous(self) -> bool:
        """Return movement control to FireBird's onboard avoidance firmware."""
        return self._write("C:A")

    def send_person_count(self, count: int) -> bool:
        return count >= 0 and self._write(f"P:{int(count)}")
