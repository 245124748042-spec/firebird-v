export interface Cell { r: number; c: number }
export type Movement = 'F' | 'B' | 'L' | 'R' | 'S'
export type DataSource = 'SIMULATED' | 'LIVE_SERIAL' | 'LIVE_PI'

export interface FireBirdTelemetry {
  leftIr: number; centerIr: number; rightIr: number; sideIr: number
  temperatureTenths: number; humidityTenths: number; smokeValue: number
  obstacleDetected: boolean; movement: Movement; riskScore: number; personCount: number
  ir5?: number | null; robotMs?: number | null; envRisk?: number | null; totalRisk?: number | null
  speed?: number | null; dhtOk?: boolean | null; flags?: number
  timestamp: string; source: DataSource
}

export type RiskLevel = 'SAFE' | 'CAUTION' | 'WARNING' | 'CRITICAL'
export interface MapCell {
  row: number; column: number; coordinate: string
  isObstacle: boolean; isPerson: boolean; isFire: boolean
  temperature: number | null; smoke: number | null
  riskScore: number; riskLevel: RiskLevel; lastUpdated: string
}
export interface MapSnapshot { rows: number; columns: number; version: number; rover: { row: number; column: number; heading: 'N' | 'E' | 'S' | 'W' }; goal?: string | null; cells: MapCell[]; odometryPath: { x: number; y: number }[]; odometryAvailable: boolean; odometryHeadingRad?: number | null; odometryStatus?: string }

export interface PlannedRoute {
  found: boolean; cells: string[]; commands: string[]
  totalCost: number; totalRisk: number; alpha: number; message: string
}
/** Optional extra fields a backend may add. The frontend computes missing ones itself. */
export interface RouteResponse extends PlannedRoute { shortestCells?: string[]; shortestRisk?: number; explanation?: string; planner?: string }
export interface RouteRequest {
  rows: number; columns: number; start: string; goal?: string; heading: 'N' | 'E' | 'S' | 'W'
  obstacles?: string[]; persons?: string[]; hazards?: { coordinate: string; riskScore: number }[]
  riskValues?: number[][]; alpha: number
}
/** Internal route state used by the UI and simulation. */
export interface RouteState {
  found: boolean; path: Cell[]; cmds: string[]; cost: number; risk: number; alpha: number; message: string
  shortestRisk: number; shortestLength: number; explanation: string; planner: 'backend' | 'local' | 'none'; status: string
}

export type Severity = 'Info' | 'Warning' | 'Critical'
export type Module = 'Obstacle' | 'Person' | 'Path' | 'Environment' | 'System'
export interface EventRec { id: number; t: number; severity: Severity; module: Module; event: string; cell: string; action: string; status: 'Open' | 'Acknowledged'; source: DataSource; backendId?: number }

export type Health = 'ok' | 'error' | 'unknown'
export interface BackendStatus {
  service: string
  serial: { connected: boolean; port: string | null; baudRate: number | null; lastTelemetryAt: string | null; error?: string | null; messagesOk?: number; messagesIgnored?: number }
  raspberryPi?: { enabled: boolean; connected: boolean; lastTelemetryAt: string | null; messagesOk: number; personCount: number | null; lastPersonCountAt: string | null }
  controller: 'online' | 'offline'
  sensors: { dht22: Health; smoke: Health }
  model: { loaded: boolean; path: string | null; error?: string | null }
  camera: { active: boolean; fps: number; latencyMs: number }
  planner: 'ready' | 'unavailable'
  battery: number | null
  mode: 'SIMULATION' | 'LIVE'
  goal?: string | null
  obstacleDetected: boolean
  fireRiskLevel: RiskLevel
  route: { state?: string; running?: boolean; paused?: boolean; index?: number; total?: number; nextCommand?: string | null; goal?: string | null; emergencyStopLatched?: boolean }
  dataSource: DataSource
}
export interface TelemetryResponse { latest: FireBirdTelemetry | null; raw: { timestamp: string; line: string }[] }
/** The backend sends upper-case severity and module (for example WARNING, OBSTACLE); the UI normalizes them. */
export interface BackendAlert { id: number; timestamp: string; severity: string; module: string; event: string; gridLocation: string; recommendedAction: string; status?: string; acknowledged?: boolean }
export interface PersonDetection { label: string; confidence: number; /** normalized [x, y, width, height], 0..1 */ box?: [number, number, number, number] }
export interface PersonStatus {
  cameraActive: boolean; count: number | null; detections: PersonDetection[]; confidenceThreshold: number; sendToFireBird: boolean
  fps: number; latencyMs: number; modelLoaded: boolean | null; modelPath: string | null; modelError: string | null
  lastSerialMessage: string | null; error: string | null
}
export type WsMessage =
  | { type: 'telemetry'; data: FireBirdTelemetry; raw?: string }
  | { type: 'map'; data: MapSnapshot }
  | { type: 'status'; data: BackendStatus }
  | { type: 'person'; data: PersonStatus }
  | { type: 'alert'; data: BackendAlert }
