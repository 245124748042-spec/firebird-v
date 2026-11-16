"""Laptop-camera person detection with Ultralytics YOLO (standard detection, not OBB).

Counts people visible in the current frame. It does not identify individuals, does no face recognition,
and never stores images."""
from __future__ import annotations

import base64
import logging
import sys
import threading
import time
from pathlib import Path
from typing import Callable, Optional

from schemas import Detection, PersonDetection

logger = logging.getLogger("firebird.vision")


class VisionService:
    def __init__(self, model_path: Path, camera_index: int, threshold: float, stable_frames: int, on_count: Callable[[int], None]) -> None:
        self.model_path, self.camera_index = model_path, camera_index
        self.threshold, self.stable_frames, self.on_count = threshold, stable_frames, on_count
        self.send_to_firebird = True
        self.safety_action = "stop"
        self.model = None
        self.model_loaded = False
        self.model_error: Optional[str] = None
        self.error: Optional[str] = None
        self.camera_active = False
        self.fps = 0.0
        self.latency_ms = 0.0
        self.count = 0
        self.detections: list[Detection] = []
        self.serial_message: Optional[str] = None
        self._jpeg: Optional[bytes] = None
        self._annotated: Optional[bytes] = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._cand, self._cand_n = 0, 0

    # ------------------------------------------------------------ model
    def load_model(self) -> bool:
        if self.model_loaded:
            return True
        if not self.model_path.is_file():
            self.model_error = "Model not found. Place trained .pt file in backend/models/."
            return False
        try:
            from ultralytics import YOLO  # imported lazily so the backend starts without it
        except ImportError:
            self.model_error = "Ultralytics is not installed. Run: pip install ultralytics"
            return False
        try:
            model = YOLO(str(self.model_path))
            if getattr(model, "task", "detect") == "obb":
                self.model_error = "This is an OBB model. Use a standard detection model."
                return False
            self.model, self.model_loaded, self.model_error = model, True, None
            logger.info("YOLO model loaded from %s", self.model_path)
            return True
        except Exception as e:  # noqa: BLE001
            self.model_error = f"Model failed to load: {e}"
            logger.exception("model load failed")
            return False

    # ------------------------------------------------------------ camera
    def start(self) -> tuple[bool, str]:
        """Start the camera and inference. Never raises."""
        if self._thread and self._thread.is_alive():
            return True, "Camera already running."
        try:
            import cv2
        except ImportError:
            self.error = "OpenCV is not installed. Run: pip install opencv-python"
            return False, self.error
        if not self.load_model():
            self.error = self.model_error
            return False, self.model_error or "Model not available."
        cap = cv2.VideoCapture(self.camera_index, cv2.CAP_DSHOW) if sys.platform.startswith("win") else cv2.VideoCapture(self.camera_index)
        if not cap.isOpened():
            cap.release()
            self.error = f"Camera {self.camera_index} could not be opened. It may be missing or in use by another application."
            return False, self.error
        self.error, self.camera_active = None, True
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, args=(cap, cv2), name="vision", daemon=True)
        self._thread.start()
        return True, "Camera started."

    def stop(self) -> None:
        self._stop.set()
        t = self._thread
        if t and t.is_alive() and t is not threading.current_thread():
            t.join(timeout=3)
        self.camera_active = False
        with self._lock:
            self.detections, self._jpeg, self._annotated = [], None, None
        self.fps = self.latency_ms = 0.0
        self._cand, self._cand_n = 0, 0
        if self.count != 0:
            self.count = 0
            self._notify(0)

    def _notify(self, n: int) -> None:
        try:
            self.on_count(n)
        except Exception:  # noqa: BLE001
            logger.exception("person count listener failed")

    def _stabilize(self, n: int) -> None:
        """Change the reported count only after the same value was seen for N consecutive frames."""
        if n == self._cand:
            self._cand_n += 1
        else:
            self._cand, self._cand_n = n, 1
        if self._cand_n >= self.stable_frames and n != self.count:
            self.count = n
            self._notify(n)  # called only when the stable count changes

    def _loop(self, cap, cv2) -> None:  # noqa: ANN001
        last = time.monotonic()
        while not self._stop.is_set():
            ok, frame = cap.read()
            if not ok:
                self.error, self.camera_active = "Camera stopped delivering frames.", False
                break
            h, w = frame.shape[:2]
            t0 = time.monotonic()
            try:
                res = self.model.predict(frame, conf=self.threshold, verbose=False)[0]
            except Exception as e:  # noqa: BLE001
                self.error = f"Inference error: {e}"
                logger.exception("inference failed")
                time.sleep(0.5)
                continue
            self.latency_ms = (time.monotonic() - t0) * 1000.0
            dets: list[Detection] = []
            for b in res.boxes:
                if str(res.names[int(b.cls[0])]).lower() != "person":
                    continue
                x1, y1, x2, y2 = (float(v) for v in b.xyxy[0].tolist())
                dets.append(Detection(label="person", confidence=round(float(b.conf[0]), 3),
                                      box=[round(x1 / w, 4), round(y1 / h, 4), round((x2 - x1) / w, 4), round((y2 - y1) / h, 4)],
                                      box_px=[int(x1), int(y1), int(x2), int(y2)]))
            ann = frame.copy()
            for i, d in enumerate(dets, 1):
                x1, y1, x2, y2 = d.box_px
                cv2.rectangle(ann, (x1, y1), (x2, y2), (200, 130, 2), 2)
                cv2.putText(ann, f"Person {i} - {d.confidence * 100:.0f}%", (x1, max(18, y1 - 6)), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (200, 130, 2), 2)
            ok1, plain = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 75])
            ok2, boxed = cv2.imencode(".jpg", ann, [cv2.IMWRITE_JPEG_QUALITY, 75])
            with self._lock:
                self.detections = dets
                if ok1:
                    self._jpeg = plain.tobytes()
                if ok2:
                    self._annotated = boxed.tobytes()
            self._stabilize(len(dets))
            now = time.monotonic()
            self.fps = 0.8 * self.fps + 0.2 / max(now - last, 1e-3)
            last = now
        cap.release()
        self.camera_active = False

    # ------------------------------------------------------------ output
    def frame_jpeg(self, annotated: bool = False) -> Optional[bytes]:
        with self._lock:
            return self._annotated if annotated else self._jpeg

    def frame_base64(self) -> Optional[str]:
        j = self.frame_jpeg()
        return base64.b64encode(j).decode("ascii") if j else None

    def status(self) -> PersonDetection:
        with self._lock:
            dets = list(self.detections)
        return PersonDetection(
            person_count=self.count, detections=dets, confidence_threshold=self.threshold, camera_active=self.camera_active,
            model_loaded=self.model_loaded, model_path=str(self.model_path), fps=round(self.fps, 1),
            inference_latency_ms=round(self.latency_ms, 1), serial_message=self.serial_message,
            count=self.count, latency_ms=round(self.latency_ms, 1), last_serial_message=self.serial_message,
            model_error=self.model_error, error=self.error, send_to_fire_bird=self.send_to_firebird, safety_action=self.safety_action)  # type: ignore[arg-type]
