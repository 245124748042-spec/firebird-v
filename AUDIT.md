# FireBird V integration audit

## Existing architecture and data flow

- `raspberry_pi/telemetry_forwarder.py` is the only Pi-side code in this workspace. It is the sole `/dev/ttyUSB0` reader, defaults to 9600 baud, and POSTs original `$FB` telemetry plus an optional YOLO count to `/api/raspberry-pi/telemetry`.
- `backend/serial_service.py` parses FireBird frames; `backend/main.py` owns REST (`/api/status`, `/api/telemetry`, `/api/map`, `/api/map/route`, `/api/person/*`), `/ws/dashboard`, camera response streaming, risk map, route planning, and odometry.
- `backend/odometry.py` integrates encoder deltas. `backend/rair_planner.py` implements 4-neighbor A* with risk cost. `backend/risk_map.py` holds obstacles, risk, pose and odometry trail.
- `frontend/src/hooks/useBackend.ts` consumes REST/WebSocket; `useRoutePlanner.ts` requests backend A* in LIVE mode; `Map3D.tsx` renders backend cells/trail/route; `CameraPanel.tsx` shows the backend's multipart stream.
- `backend/vision_service.py` is a laptop-local camera capture/inference pipeline. Pi mode explicitly disables its camera status; `/api/person/stream` serves only this local capture. There is no Pi camera capture or frame-forwarding code in the repository.

## Findings before edits

1. Serial configuration and packet parsing already retain 9600 baud, the existing `$FB` frame, and one Pi serial reader. No serial or firmware changes are needed or planned.
2. Odometry is already differential-drive and uses configured wheel diameter/track, encoder counts, and PPR. The actual diameter and track are set to 0.05 m and 0.155 m. `MAP_CELL_SIZE_M` is unset, which makes calibration invalid and disables encoder pose projection. PPR is currently configured as 32, but this workspace contains no evidence validating that value against the installed encoder; it must be confirmed, not guessed. The map has no metric resolution calibration.
3. Route display is already backed by the live risk/obstacle grid and A*. The missing destination is a UI integration gap: live route planning requires a backend map goal, but the 3D canvas does not convert pointer selection into a destination; the planner panel says destination selection will be added later. The planner returns an explicit no-destination response until a goal is supplied.
4. Pi telemetry forwards counts but no image frames. The dashboard and backend correctly state that the Pi preview is unavailable. The Pi detector/capture implementation is outside this project, so adding another camera opener here would risk competing for `/dev/video0` and would not meet the shared capture requirement.

## Safe integration plan

- Preserve serial protocol, baud, firmware, motor commands and telemetry fields.
- Add map destination selection using existing backend A* and render the returned route on the same backend grid.
- Keep encoder mapping disabled until the missing metric cell size and verified encoder PPR are supplied; surface the calibration state clearly.
- Do not add a second camera capture process. Provide the backend/UI side only if a safe shared-frame sender can be integrated with the external Pi detector; that source is not available here.
