#!/usr/bin/env python3
"""Forward newline-terminated FireBird $FB telemetry to the laptop backend."""
from __future__ import annotations

import argparse
import json
import logging
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import serial

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
LOG = logging.getLogger("firebird-forwarder")
WIRE_COMMANDS = {"MOVE:FORWARD": "C:F", "MOVE:BACKWARD": "C:B", "MOVE:LEFT": "C:L",
                 "MOVE:RIGHT": "C:R", "MOVE:STOP": "C:S"}


def read_person_count(path: Path | None, max_age_s: float = 3.0) -> int | None:
    if path is None:
        return None
    try:
        if time.time() - path.stat().st_mtime > max_age_s:
            return None
        value = int(path.read_text(encoding="utf-8").strip())
        return value if value >= 0 else None
    except (OSError, ValueError):
        return None


def post_frame(url: str, line: str, person_count: int | None, timeout: float) -> None:
    payload: dict[str, object] = {"line": line}
    # Null means the detector count is unavailable; the backend must not
    # present the firmware's unrelated `persons` field as a YOLO result.
    payload["personCount"] = person_count
    request = Request(url, data=json.dumps(payload).encode("utf-8"), headers={"Content-Type": "application/json"}, method="POST")
    with urlopen(request, timeout=timeout) as response:
        if response.status < 200 or response.status >= 300:
            raise RuntimeError(f"Backend returned HTTP {response.status}")


def poll_command(url: str, timeout: float) -> dict:
    with urlopen(Request(url, headers={"Accept": "application/json"}), timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def acknowledge_command(url: str, command_id: int, accepted: bool, error: str | None, timeout: float) -> None:
    payload = {"accepted": accepted, "error": error}
    request = Request(url.format(command_id=command_id), data=json.dumps(payload).encode("utf-8"),
                      headers={"Content-Type": "application/json"}, method="POST")
    with urlopen(request, timeout=timeout) as response:
        if response.status < 200 or response.status >= 300:
            raise RuntimeError(f"Backend rejected command acknowledgement (HTTP {response.status})")


def best_effort_stop(port, reason: str) -> None:  # noqa: ANN001
    try:
        port.write(b"C:S\n")
        port.flush()
        LOG.critical("Sent existing C:S stop command after %s", reason)
    except (OSError, serial.SerialException) as exc:
        LOG.critical("Could not send C:S after %s: %s", reason, exc)


def run(args: argparse.Namespace) -> None:
    endpoint = args.backend.rstrip("/") + "/api/raspberry-pi/telemetry"
    command_endpoint = args.backend.rstrip("/") + "/api/raspberry-pi/command/next"
    ack_endpoint = args.backend.rstrip("/") + "/api/raspberry-pi/command/{command_id}/ack"
    count_path = Path(args.person_count_file) if args.person_count_file else None
    backoff = 1.0
    navigation_active = False
    while True:
        try:
            with serial.Serial(args.port, args.baud, timeout=0.1, write_timeout=1) as port:
                LOG.info("Reading %s at %d baud; forwarding to %s", args.port, args.baud, endpoint)
                backoff = 1.0
                last_command_poll = 0.0
                while True:
                    line = port.readline().decode("ascii", errors="ignore").strip()
                    if line and not line.startswith("$FB"):
                        LOG.debug("Skipping non-$FB serial line: %s", line[:120])
                    if line.startswith("$FB"):
                        try:
                            post_frame(endpoint, line, read_person_count(count_path, args.person_count_max_age), args.timeout)
                        except (HTTPError, URLError, TimeoutError, OSError, RuntimeError) as exc:
                            if navigation_active:
                                best_effort_stop(port, "telemetry forwarding failure")
                                navigation_active = False
                            LOG.warning("Telemetry forward failed (%s); retaining the sole serial reader", exc)

                    now = time.monotonic()
                    if now - last_command_poll < args.command_poll_interval:
                        continue
                    last_command_poll = now
                    try:
                        status = poll_command(command_endpoint, args.command_timeout)
                        navigation_active = bool(status.get("missionActive"))
                        command_id, command = status.get("commandId"), status.get("command")
                        if command_id is None:
                            continue
                        age_ms, ttl_ms = status.get("ageMs", 0), status.get("ttlMs", 0)
                        if command not in WIRE_COMMANDS or not isinstance(age_ms, int) or not isinstance(ttl_ms, int) or age_ms >= ttl_ms:
                            error = "Unknown or stale command"
                            acknowledge_command(ack_endpoint, int(command_id), False, error, args.command_timeout)
                            if navigation_active:
                                best_effort_stop(port, "stale command rejection")
                            continue
                        try:
                            port.write((WIRE_COMMANDS[command] + "\n").encode("ascii"))
                            port.flush()
                        except (OSError, serial.SerialException) as exc:
                            acknowledge_command(ack_endpoint, int(command_id), False, str(exc), args.command_timeout)
                            if navigation_active:
                                best_effort_stop(port, "command write failure")
                            raise
                        acknowledge_command(ack_endpoint, int(command_id), True, None, args.command_timeout)
                    except (HTTPError, URLError, TimeoutError, OSError, RuntimeError, ValueError) as exc:
                        if navigation_active:
                            best_effort_stop(port, "laptop command link failure")
                            navigation_active = False
                        LOG.warning("Command bridge unavailable (%s)", exc)
        except (serial.SerialException, OSError) as exc:
            if navigation_active:
                # A serial disconnect leaves no local route to send C:S.
                LOG.critical("Serial connection lost during navigation; no command can reach FireBird: %s", exc)
                navigation_active = False
            LOG.warning("Serial unavailable (%s); retrying in %.1f s", exc, backoff)
            time.sleep(backoff)
            backoff = min(backoff * 2, 15.0)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", default="/dev/ttyUSB0")
    parser.add_argument("--baud", type=int, default=9600)
    parser.add_argument("--backend", default="http://192.168.62.175:8000", help="Laptop backend base URL")
    parser.add_argument("--person-count-file", default="/home/pi/person_detection/person_count.txt",
                        help="File containing the current YOLO count (default: %(default)s)")
    parser.add_argument("--person-count-max-age", type=float, default=3.0,
                        help="Ignore count files older than this many seconds")
    parser.add_argument("--timeout", type=float, default=2.0)
    parser.add_argument("--command-timeout", type=float, default=0.5)
    parser.add_argument("--command-poll-interval", type=float, default=0.1)
    run(parser.parse_args())


if __name__ == "__main__":
    main()
