# FireBird Backend (PC side)

Local Python backend for **FireBird: AI-Based Autonomous Hazard Detection and Dynamic Risk Mapping Rover**. It reads FireBird telemetry over serial or from the Raspberry Pi Wi-Fi forwarder, runs optional YOLO person detection on the laptop camera, keeps a risk map, plans routes with A* and a RAIR-inspired risk-attitude planner, and serves a REST + WebSocket API for the React dashboard. No database or cloud service is required.

FireBird itself runs **no** A*, RAIR or YOLO. It reads sensors, avoids obstacles, reports telemetry and executes high-level commands. It keeps final physical safety authority.

## Architecture

```
FireBird V (ATmega2560 + ATmega8)            PC (this backend)                           React dashboard
 5 IR, DHT22, smoke, LCD, motors   --USB-->  serial_service  --> risk_map --> rair_planner      http://localhost:5173
                                    --USB--> Raspberry Pi --Wi-Fi--> /api/raspberry-pi/telemetry
 telemetry out, MOVE:* / P:n in    <------   route_executor        |             ^                    ^
                                             vision_service (YOLO, laptop camera) |  REST + /ws/dashboard
                                             simulation_service (only when no robot)  alert_service ---+
```

## Features

- **Two modes, always explicit.** `LIVE` only while either USB serial or the Raspberry Pi Wi-Fi forwarder is delivering valid telemetry within `LIVE_TIMEOUT_S` (3 s). Otherwise `SIMULATION`, and every simulated sample has `source: "SIMULATED"`. Real data has source `LIVE_SERIAL` or `LIVE_PI`.
- Safe serial parsing for `$FB` CSV and the legacy keyed format, telemetry-verified connections, a single reader/port owner, and disconnect fallback to simulation.
- Grid map 5 x 5 to 20 x 20 (rows A.., columns 1..), risk spread `neighbor_risk = source_risk * exp(-k * distance)`, risk decay, blocked cells.
- Standard A* and RAIR-inspired A*, comparison with the shortest route, route executor with obstacle pause and replanning.
- YOLO person detection (standard detection, class `person` only), count stabilized over N frames, `P:<n>` sent only when the stable count changes.
- Alerts, WebSocket broadcast to many dashboards, CORS for `http://localhost:5173` and `http://localhost:3000`.
- Starts fine with no robot, no camera and no model file.

## Prerequisites

Python 3.10+, a webcam (optional), FireBird with USB cable (optional), the trained model file (optional).

## Installation

```bash
cd firebird-backend
python -m venv venv
venv\Scripts\activate           # Windows   (Linux/macOS: source venv/bin/activate)
pip install -r requirements.txt
copy config.example.env .env    # Linux/macOS: cp config.example.env .env
```

## Run

```bash
python main.py
# or
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

Interactive API docs: http://localhost:8000/docs

## Configuration (`.env`)

| Variable | Default | Meaning |
|---|---|---|
| `RASPBERRY_PI_MODE` | `false` | In Pi mode, never open a laptop serial port and receive Pi Wi-Fi telemetry |
| `SERIAL_PORT` | `COM3` | FireBird USB serial port when Pi mode is disabled; ignored in Pi mode |
| `BAUD_RATE` | 9600 | Must match the FireBird firmware |
| `MODEL_PATH` | models/firebird_person_yolov8n_best.pt | Relative to this folder |
| `CAMERA_INDEX` | 0 | Laptop camera |
| `CONFIDENCE_THRESHOLD` | 0.60 | 0.30 to 0.90 |
| `PERSON_COUNT_STABLE_FRAMES` | 3 | Same count needed for this many frames |
| `SIMULATION_TICK_MS` | 200 | Simulator step |
| `MAP_ROWS`, `MAP_COLUMNS` | 10 | 5 to 20 |
| `CORS_ORIGINS` | localhost:5173, localhost:3000 | Comma separated |
| `HOST`, `PORT` | `0.0.0.0`, `8000` | Backend bind address and port |

Optional tuning (same file): `W_OBS=0.35 W_PERSON=0.25 W_THERMAL=0.20 W_SMOKE=0.15 W_HEALTH=0.05`, `RISK_COST_SCALE=40`, `RISK_SPREAD_K_*`, `RISK_DECAY_PER_S`, `SMOKE_BASELINE=150`, `SMOKE_HIGH=600`, `LIVE_TIMEOUT_S`. **Calibrate `SMOKE_BASELINE`/`SMOKE_HIGH` for your smoke sensor.** Invalid values stop the server with a clear message.

Put your model at `models/firebird_person_yolov8n_best.pt`. If it is missing, the backend still starts and reports "Model not found. Place trained .pt file in backend/models/."

## Serial protocol (newline-terminated, 9600 baud)

FireBird to PC every 300 to 500 ms:
`L:<ir1>,C:<ir2>,R:<ir3>,S:<ir4>,T:<temp tenths>,H:<humidity tenths>,SM:<smoke ADC>,OBS:<0|1>,MOVE:<F|B|L|R|S>,RISK:<0-100>,PC:<n>`
Example: `L:565,C:602,R:647,S:576,T:271,H:453,SM:180,OBS:0,MOVE:F,RISK:18,PC:0`

PC to FireBird: `MOVE:FORWARD`, `MOVE:LEFT`, `MOVE:RIGHT`, `MOVE:STOP`, and `P:0`, `P:1`, `P:2`... Only these are ever sent. Raw PWM is never sent (the code refuses anything else).

Assumptions to confirm with your firmware: one `MOVE:FORWARD` moves one grid cell and one `LEFT`/`RIGHT` turns 90 degrees, after which `MOVE` returns to `S`. The backend dead-reckons the rover pose when it sees `MOVE:S` at least 1 s after a command; this can drift. There is no battery field, so battery is `null` in live mode.

## Simulation mode

When no valid telemetry is arriving, `simulation_service` generates telemetry every `SIMULATION_TICK_MS`, moves a simulated rover on the map, and derives IR values, temperature, humidity, smoke and risk from the map's hazards (add a hotspot and the simulated rover reads hot nearby). Control it with `POST /api/simulation` (`start`, `pause`, `reset`, speed 0.5 / 1 / 2). It stops by itself when LIVE MODE begins.

## Connecting FireBird

1. Plug in USB, find the port (Windows Device Manager, Linux `ls /dev/ttyUSB*`).
2. Set `SERIAL_PORT=COM3` in `.env` and restart, or press Connect Robot. Connection succeeds only after valid telemetry arrives.
3. Check `GET /api/status`: `mode` becomes `LIVE` only after the first valid telemetry line.

## Risk map and planner

- Cell `risk_score` (0 to 100) is the strongest hazard component. Levels: SAFE 0-24, CAUTION 25-49, WARNING 50-74, CRITICAL 75-100. Obstacles, fire cells, person cells and CRITICAL cells are **blocked**.
- Planner risk: `risk(n) = 0.35*obstacle + 0.25*person + 0.20*thermal + 0.15*smoke + 0.05*health` (each 0..1).
- RAIR-inspired A*: `f(n) = g(n) + h(n) + alpha * risk(n)`, implemented by adding `alpha * RISK_COST_SCALE * risk(n)` to the cost of every cell entered (so `g` already holds accumulated risk). **alpha 0.5 = risk-seeking, 1.5 = neutral, 3.0 = risk-averse, 5.0 = highly risk-averse.** `risk_aware: false` gives standard A*.
- This is RAIR-**inspired**, not the published RAIR algorithm.
- Person detections from the camera are not localized; the cell ahead of the rover is marked as an approximation and fades when the count returns to 0.

### Calculate a route

```bash
curl -X POST localhost:8000/api/map/route -H "Content-Type: application/json" \
  -d '{"startRow":9,"startColumn":0,"goalRow":0,"goalColumn":9,"riskAttitudeAlpha":3.0,"riskAware":true}'
```
### Send it to FireBird

Add `"sendRoute": true` to the same request, or call `POST /api/route/start` afterwards. The executor sends one command at a time, waits for `MOVE:S`, never sends FORWARD while `OBS:1`, and on `OBS:1` stops, marks the cell ahead as blocked, replans and continues. Pause, resume or stop with `POST /api/route/pause|resume|stop`.

### Person detection

`POST /api/person/start` (optional body `{"confidenceThreshold":0.6,"sendToFireBird":true}`), view `GET /api/person/stream`, stop with `POST /api/person/stop`. Safety action (`ignore`, `slow`, `stop`; default `stop`): `POST /api/person/safety-action`. This counts people in the current frame only. It does not identify people and stores no images.

## API reference

JSON is camelCase. snake_case is also accepted in request bodies. Errors: `{"detail": "message"}` with 400, 409 or 422.

| Endpoint | Request | Response (sample) |
|---|---|---|
| `GET /api/health` | - | `{"status":"ok","mode":"SIMULATION","serial":{...},"simulation":{"running":true,"speed":1.0,"tick":52},"camera":{...},"model":{"loaded":false,...},"planner":"ready","lastTelemetryTimestamp":"2026-..."}` |
| `GET /api/status` | - | `{"mode":"LIVE","dataSource":"LIVE_SERIAL","serial":{"connected":true,"port":"COM5","baudRate":9600},"controller":"online","sensors":{"dht22":"ok","smoke":"ok"},"rover":{"coordinate":"J1","heading":"N"},"goal":"A10","movement":"S","obstacleDetected":false,"personCount":0,"temperatureC":27.1,"humidityPct":45.3,"smokeValue":180,"fireRiskLevel":"SAFE","battery":null,"route":{"state":"IDLE"}}` |
| `GET /api/telemetry` | - | `{"latest":{"leftIr":565,"centerIr":602,"rightIr":647,"sideIr":576,"temperatureTenths":271,"humidityTenths":453,"smokeValue":180,"obstacleDetected":false,"movement":"F","riskScore":18,"personCount":0,"timestamp":"...","source":"LIVE_SERIAL"},"mode":"LIVE","raw":[{"timestamp":"...","line":"L:565,..."}]}` |
| `POST /api/command` | `{"command":"MOVE:FORWARD"}` | `{"success":true,"message":"Command sent to FireBird.","command":"MOVE:FORWARD","mode":"LIVE","state":{...}}`. 409 if refused (OBS:1, person stop) |
| `POST /api/map/route` | `{"start":"J1","goal":"A10","riskAttitudeAlpha":1.5,"riskAware":true,"obstacles":["C3",{"row":5,"column":5}],"persons":[],"hazards":[{"coordinate":"E4","riskScore":80}],"sendRoute":false}`. Also accepts `startRow/startColumn/goalRow/goalColumn`, `rows/columns`, `heading`, `riskValues`, `alpha` | `{"found":true,"cells":["J1","I1"],"commands":["MOVE:FORWARD","MOVE:STOP"],"totalCost":18.0,"totalRisk":21.6,"alpha":3.0,"message":"Route found.","shortestCells":[...],"shortestLength":18,"shortestRisk":79.3,"extraMoves":0,"explanation":"...","routeSent":false}`. `found:false` with "No safe route found." if none |
| `POST /api/map/cell` | `{"row":3,"column":6,"action":"ADD_HOTSPOT"}` (ADD/REMOVE_OBSTACLE, ADD/REMOVE_PERSON, ADD/REMOVE_HOTSPOT, CLEAR_CELL) or flags `{"row":4,"column":4,"isObstacle":true}` | `{"success":true,"applied":["ADD_HOTSPOT"],"cell":{"coordinate":"D7","riskScore":85.0,"riskLevel":"CRITICAL",...}}` |
| `GET /api/map` | - | `{"rows":10,"columns":10,"version":12,"rover":{...},"goal":"A10","cells":[MapCell,...]}` |
| `POST /api/map/resize` / `clear` | `{"rows":12,"columns":12}` | map meta |
| `GET /api/alerts` | `?severity=WARNING&module=PATH&acknowledged=false` | `[{"id":3,"timestamp":"...","severity":"WARNING","module":"OBSTACLE","event":"Obstacle detected. Route paused. Replanning required.","gridLocation":"E5","recommendedAction":"Replanning route","acknowledged":false,"status":"Open"}]` |
| `POST /api/alerts/acknowledge` | `{"id":3}` or `{"ids":[1,2]}` or `{"ids":"all"}` | `{"success":true,"acknowledged":1}` |
| `POST /api/alerts/clear-noncritical` | `{}` | `{"success":true,"cleared":11}` |
| `GET /api/person/status` | - | `{"personCount":2,"count":2,"detections":[{"label":"person","confidence":0.94,"box":[0.1,0.2,0.3,0.6],"boxPx":[64,96,256,480]}],"confidenceThreshold":0.6,"cameraActive":true,"modelLoaded":true,"modelPath":"...","fps":14.8,"inferenceLatencyMs":52.3,"serialMessage":"P:2","sendToFireBird":true,"safetyAction":"stop"}` |
| `POST /api/person/start` / `stop` | optional body above | status as above, 409 with reason if the model or camera is unavailable |
| `GET /api/person/stream` | `?annotated=true` optional | MJPEG. `GET /api/person/frame` gives one base64 JPEG |
| `POST /api/serial/connect` / `disconnect` | `{"port":"COM3","baudRate":9600}` | Success after a valid telemetry frame is received |
| `POST /api/raspberry-pi/telemetry` | `{"line":"$FB,...","personCount":1}` | Validates the original FireBird frame and receives a Pi YOLO count with server receive timestamp |
| `POST /api/raspberry-pi/person-count` | `{"personCount":1}` | Receives a count-only update with server timestamp |
| `GET/POST /api/simulation` | `{"action":"pause","speed":0.5}` | `{"running":false,"speed":0.5,"tick":52,"mode":"SIMULATION"}` |
| `GET /api/route`, `POST /api/route/start\|pause\|resume\|stop` | - | `{"executor":{"state":"FOLLOWING","index":3,"total":18,...}}` |
| `WS /ws/dashboard` | - | Messages `{"type": "telemetry\|status\|map\|route\|person\|alert", "data": {...}, "raw": "..."}`. A snapshot (status, telemetry, map, person, recent alerts) is sent on connect. Send the text `ping` to get `pong` |

Frontend compatibility: `LIVE_SERIAL` and `LIVE_PI` telemetry are real; simulated telemetry is labelled `SIMULATED`.

### Raspberry Pi Wi-Fi forwarding

The backend accepts the Pi's original newline-terminated FireBird `$FB` frames at `POST /api/raspberry-pi/telemetry` with JSON `{"line":"$FB,..."}` and an optional `personCount` integer. It runs the same parser as USB serial, so the firmware field mapping is shared. Pi readings are labelled `LIVE_PI`; after `LIVE_TIMEOUT_S` without a valid frame the status is disconnected and simulation mode begins. Pi mode skips opening the laptop serial port, disables USB connect attempts and rejects movement commands because this forwarder is telemetry-only. Last received real values remain visible in the dashboard after a disconnect and are marked stale instead of being replaced by simulated readings. Start the forwarder on the Pi using [the Pi setup guide](../raspberry_pi/README.md). The laptop backend binds to `0.0.0.0:8000` by default.

## Troubleshooting

- **COM port not found:** check Device Manager, close other programs using the port (Arduino/AVR Studio terminal), then `POST /api/serial/connect`. The backend stays in SIMULATION MODE meanwhile.
- **Serial permission error (Linux):** `sudo usermod -a -G dialout $USER`, log out and in.
- **Camera not opening:** try `CAMERA_INDEX=1`, close other apps using the camera. The error appears in `/api/person/status`.
- **Model file missing:** put the `.pt` in `models/` or fix `MODEL_PATH`. OBB models are rejected.
- **CORS error:** add your dashboard origin to `CORS_ORIGINS` and restart.
- **WebSocket disconnects:** the dashboard reconnects automatically. Make sure the backend is running and nothing else uses port 8000.
- **Stays in SIMULATION with the port open:** no valid telemetry lines. Watch `serial.messagesIgnored` in `/api/status`; check baud rate and the line format.

## Safety notes

## FireBird `$FB` CSV and Windows quick start

FireBird V telemetry is received at 9600 baud. The existing frame remains accepted unchanged; encoder firmware may append cumulative unsigned left and right pulse counts after all existing fields: `$FB,ms,IR1,IR2,IR3,IR4,IR5,temp_x10,hum_x10,smoke,env_risk,total_risk,persons,dir,speed,dht_ok,flags,mode,left_count,right_count`. Backend parsing accepts both old (18 total CSV fields including `$FB`) and extended (20 total) formats. For odometry set measured `WHEEL_DIAMETER_M`, `WHEEL_TRACK_M`, `ENCODER_PULSES_PER_REVOLUTION`, and `MAP_CELL_SIZE_M` in `.env`; until then, the dashboard displays no encoder path and command-based pose tracking remains active. The first pair initializes the baseline and preserves the current map pose and heading. Cumulative uint32 rollover is handled. These encoders count rising edges only and do not measure direction; the backend uses the FireBird movement field (`F/B/L/R`) to sign each interval. Manual pushing, coasting, and movement-direction changes within an interval are not measured reliably. Command-based pose updates are suppressed while calibrated live encoder odometry is active. The physical firmware source is not included in this workspace, so firmware integration remains outstanding.

Install Python 3.10+ and Node.js first. From the project root, in two PowerShell terminals:

```powershell
cd backend
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python main.py
```

```powershell
cd frontend
npm install
npm run dev
```

Connect FireBird on COM3 and close any serial monitor using that port, then press **Connect Robot**. Success requires a valid telemetry frame. Check `http://localhost:8000/api/status` for `mode: LIVE`, `dataSource: LIVE_SERIAL`, and increasing `serial.messagesOk`; `/api/telemetry` exposes latest parsed values. No database is configured, so raw lines are kept in a bounded in-memory log.

## Safety notes

Test at low speed with an emergency stop available. FireBird's onboard obstacle avoidance has highest priority and the backend never overrides it. Do not use near real fire. This is a prototype, not a certified safety or fire-alarm system.
