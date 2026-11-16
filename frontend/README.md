# FireBird Dashboard (React frontend)

Frontend for **FireBird: AI-Based Autonomous Hazard Detection and Dynamic Risk Mapping Rover**. It talks to a local Python FastAPI backend (serial telemetry, YOLO person detection, route planning, alerts) and works on its own in simulation.

## Run

```bash
npm install
npm run dev          # http://localhost:5173
```

Backend URL: copy `.env.example` to `.env` and change `VITE_API_BASE_URL` if needed (default `http://localhost:8000`). No database, login, API key or paid service is used.

## Simulation mode and live mode

| | SIMULATION MODE | LIVE MODE |
|---|---|---|
| When | Backend offline, robot not connected, or no serial telemetry in the last 4 s | Backend reports an open serial port **and** real `LIVE_SERIAL` telemetry is arriving |
| Badge | "SIMULATION MODE — No live robot connected" | "LIVE MODE — FireBird connected on COMx" |
| Sensor values | Generated in the browser, badged `SIMULATED` | Only backend telemetry, badged `LIVE SERIAL` |

Telemetry with `source: "SIMULATED"` from the backend is never treated as live. When the mode changes, obstacles, start, goal, grid size and alpha are kept; simulated scenarios and chart history are reset. If the backend is offline the UI shows "Backend service offline" and keeps working in simulation.

## Features

- **Command Center:** rover status, position, goal, battery, movement, obstacle, person count, temperature, humidity, smoke, max temperature, fire-risk level, four status tiles, risk map, alerts, activity timeline
- **Map and Route:** 5 x 5 to 20 x 20 grid (A to T, 1 to 20), risk colours, edit tools, cell details, risk-attitude slider (alpha 0.5 to 5.0, default 1.5), route risk versus shortest route, command queue, simulated rover animation, pause/resume, automatic pause, obstacle marking and replanning on obstacle
- **Person Detection:** camera stream with YOLO boxes, count, confidence, FPS, latency, model status, LCD preview, threshold slider, send-count toggle, safety action (Ignore / Slow down / Stop rover)
- **Environment and Fire:** temperature, humidity and smoke charts, fire-risk gauge, scenarios, "Why this risk level?", 32 x 24 simulated heatmap placeholder
- **Telemetry and Alerts:** serial console, filters, alert table, acknowledge, clear noncritical, CSV export, event-frequency chart
- **System Health:** diagnostic checklist including DHT22 and smoke sensor status

## About the planner

The "RAIR" planner is **RAIR-inspired, not the published algorithm**: A* with step cost `1 + 0.1 * alpha * risk`. Alpha follows the backend: 0.5 = risk-seeking, 1.5 = neutral, 3.0 = risk-averse, 5.0 = highly risk-averse (higher alpha = stronger risk penalty). Critical cells (risk 70 or more) and obstacles are never entered. The frontend sends `POST /api/map/route`; if the backend is offline or fails, it uses the same logic locally and labels it "LOCAL SIMULATION PLANNER".

## Backend contract (what the frontend expects)

All JSON, camelCase. Types are in `src/types/index.ts`.

| Endpoint | Purpose |
|---|---|
| `GET /api/health`, `GET /api/status` | `BackendStatus`: `serial{connected,port,baudRate,lastTelemetryAt}`, `controller`, `sensors{dht22,smoke}`, `model`, `camera`, `planner`, `battery` |
| `GET /api/telemetry` | `{latest: FireBirdTelemetry, raw: [{timestamp, line}]}` |
| `POST /api/command` | `{command: "MOVE:FORWARD"}` (also LEFT, RIGHT, STOP) |
| `POST /api/map/route` | `RouteRequest` in, `PlannedRoute` out (`found, cells[], commands[], totalCost, totalRisk, alpha, message`). Optional extras: `shortestCells, shortestRisk, explanation` |
| `POST /api/map/cell` | Best-effort cell sync (`MapCell`) |
| `GET /api/alerts`, `POST /api/alerts/acknowledge` | `BackendAlert[]` (upper-case severity/module are normalized), body `{ids: number[] or "all"}` |
| `GET /api/person/status` | `PersonStatus` (count already stabilized over 3 frames by the backend, detections with normalized `box [x,y,w,h]`) |
| `POST /api/person/start` / `stop` | start body `{confidenceThreshold, sendToFireBird}`; calling start again applies new settings |
| `WS /ws/dashboard` | messages `{type: "telemetry"\|"status"\|"person"\|"alert", data, raw?}` |

**Assumed extras (not in your endpoint list):** `GET /api/person/stream` (plain MJPEG, boxes are drawn by the frontend), and `POST /api/serial/connect` / `/api/serial/disconnect` for the Connect Robot buttons. If missing, the UI shows a warning instead of crashing.

Serial line shown in the console: `L:42,C:18,R:55,T:271,H:453,SM:180,OBS:1,MOVE:S,RISK:76,PC:2` (temperature and humidity in tenths). Smoke is a raw value; alert thresholds (`TEMP_WARN/CRIT`, `SMOKE_WARN/CRIT` in `src/lib/format.ts`) are defaults, so calibrate them for your sensor.

## Structure

```
src/
  components/  Card, Badge, Button, Header, Home, StatusTile, MetricTile, ArenaMap, StatusTiles, Controls,
               Charts, EventLog, PersonDetection, EnvironmentMonitoring, TelemetryConsole, SystemHealth,
               RoutePlanner, CommandCenter, MapPage, CellDetails
  hooks/       useBackend (REST + WebSocket), useSimulation (200 ms loop), useRoutePlanner, useDashboard (context)
  lib/         api, simulation (pure engine), mapUtils (risk grid, A*, commands), format
  types/       index.ts
```
Extra files beyond your list: `CommandCenter`, `MapPage`, `CellDetails`, `hooks/useDashboard.tsx`, `src/vite-env.d.ts`.

## Hardware integration notes

- One `MOVE:FORWARD` is assumed to move one grid cell and one `LEFT`/`RIGHT` a 90-degree turn; the dashboard advances its estimated position after the robot reports `S` (stopped). Position is dead-reckoned and can drift.
- Obstacle (`obstacleDetected`) during route following: the dashboard sends STOP, marks the cell ahead, shows "Obstacle detected. Route paused. Replanning required.", replans and resumes.
- "Slow down" has no speed command, so the dashboard waits 2.5 s between commands while a person is visible.
- Thermal/fire monitoring is decision support only, not a certified fire-alarm system. There is no flame sensor or thermal camera in the telemetry, so the heatmap is always a simulated placeholder.
