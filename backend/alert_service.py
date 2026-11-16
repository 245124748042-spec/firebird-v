"""In-memory alert list with acknowledge, filter and clear."""
from __future__ import annotations

import logging
import threading
import time
from collections import deque
from typing import Callable, Optional

from schemas import Alert, utcnow

logger = logging.getLogger("firebird.alerts")


class AlertService:
    def __init__(self, max_alerts: int = 300) -> None:
        self._lock = threading.Lock()
        self._alerts: deque[Alert] = deque(maxlen=max_alerts)
        self._next_id = 1
        self._recent: dict[str, float] = {}
        self.on_new: Optional[Callable[[Alert], None]] = None  # set by main to push alerts to dashboards

    def add(self, severity: str, module: str, event: str, grid_location: str = "-", action: str = "None", dedupe_s: float = 2.0) -> Optional[Alert]:
        """Add an alert. The same event is ignored if it repeats within `dedupe_s` seconds."""
        key = f"{module}|{event}|{grid_location}"
        now = time.monotonic()
        with self._lock:
            if now - self._recent.get(key, -1e9) < dedupe_s:
                return None
            self._recent[key] = now
            alert = Alert(id=self._next_id, timestamp=utcnow(), severity=severity, module=module, event=event,  # type: ignore[arg-type]
                          grid_location=grid_location, recommended_action=action)
            self._next_id += 1
            self._alerts.appendleft(alert)
        logger.log(logging.WARNING if severity != "INFO" else logging.INFO, "ALERT %s %s: %s", severity, module, event)
        if self.on_new:
            try:
                self.on_new(alert)
            except Exception:  # noqa: BLE001
                logger.exception("alert listener failed")
        return alert

    def list(self, severity: Optional[str] = None, module: Optional[str] = None, acknowledged: Optional[bool] = None) -> list[Alert]:
        with self._lock:
            return [a for a in self._alerts
                    if (severity is None or a.severity == severity.upper())
                    and (module is None or a.module == module.upper())
                    and (acknowledged is None or a.acknowledged == acknowledged)]

    def acknowledge(self, ids: Optional[list[int]] = None) -> int:
        """Acknowledge the given ids, or all alerts when ids is None."""
        n = 0
        with self._lock:
            for a in self._alerts:
                if (ids is None or a.id in ids) and not a.acknowledged:
                    a.acknowledged = True
                    n += 1
        return n

    def clear_noncritical(self) -> int:
        with self._lock:
            before = len(self._alerts)
            self._alerts = deque((a for a in self._alerts if a.severity == "CRITICAL"), maxlen=self._alerts.maxlen)
            return before - len(self._alerts)
