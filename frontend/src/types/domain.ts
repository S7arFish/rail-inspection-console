/**
 * Wire types mirroring the FastAPI contract (backend/app/schemas.py).
 * Keep both sides in lockstep when a field changes.
 */

/**
 * The DHJ-9 exports on demand: the operator presses 导出记录, the device dumps a
 * batch, `OVER` closes it and the link waits again. One batch is one session.
 */
export type SerialState =
  | 'disconnected'
  | 'connecting'
  | 'connected_waiting'
  | 'receiving'
  | 'batch_complete'
  | 'error'
  | 'reconnecting'

/** Where a live frame came from. `dhj9` is the laser detector. */
export type LiveSource = 'dhj9' | 'console' | (string & {})

/**
 * Platform-neutral: `device` is `COM7` on Windows and `/dev/ttyUSB0` on Linux.
 * Nothing may assume a `COM` prefix.
 */
export interface PortInfo {
  device: string
  name: string
  description: string | null
  hwid: string | null
  manufacturer: string | null
  vid: number | null
  pid: number | null
  serial_number: string | null
  suggested: boolean
}

export interface PortsResponse {
  ports: PortInfo[]
  suggested_port: string | null
  error: string | null
}

export interface SerialStatus {
  state: SerialState
  port: string | null
  baud_rate: number | null
  data_bits: number | null
  parity: string | null
  stop_bits: number | null
  flow_control: string | null
  session_id: string | null
  sample_count: number
  batch_count: number
  /** rows of the batch still arriving; 0 while waiting or after OVER */
  records_in_batch: number
  last_line_at: string | null
  last_error: string | null
  rx_line_count: number
  parse_error_count: number
  uptime_ms: number | null
}

export interface ConnectRequest {
  port?: string
  baud_rate?: number
  data_bits?: number
  parity?: string
  stop_bits?: number
  flow_control?: string
  session_note?: string
}

export interface ConnectResponse {
  ok: boolean
  session_id: string | null
  state: SerialState
  port: string | null
  baud_rate: number | null
  message: string
}

/** `confirmed: false` means the field name is still an assumption. */
export interface ParserField {
  index: number
  name: string
  type: 'int' | 'float' | 'string' | 'timestamp'
  unit: string | null
  confirmed: boolean
  note: string | null
}

export interface ParserFieldsResponse {
  fields: ParserField[]
  timestamp_field: number
  timestamp_format: string
  end_of_batch_token: string
  expected_field_count: number
}

export type SessionStatus = 'running' | 'completed' | 'interrupted' | 'failed'

export interface SessionRecord {
  id: string
  started_at: string
  ended_at: string | null
  port: string
  baud_rate: number
  status: SessionStatus
  sample_count: number
  batch_count: number
  source: string
  note: string | null
}

export interface Measurement {
  id: number
  session_id: string
  ts_raw: string | null
  ts: string | null
  /** keyed by configured parser field names */
  fields: Record<string, number | string | null>
  raw_line: string
  batch_seq: number
  created_at: string
}

export interface SessionListResponse {
  items: SessionRecord[]
  total: number
}

export interface SessionDetailResponse {
  session: SessionRecord
  samples: Measurement[]
  latest: Measurement | null
  count: number
}

export interface HealthResponse {
  status: string
  version: string
  db_path: string
  serial_state: SerialState
}

/** Every frame: `{ type, source, timestamp, payload }`. */
export interface LiveEnvelope<T = unknown> {
  type: string
  source: LiveSource
  timestamp: string
  payload: T
}

export type LiveEvent =
  | LiveEnvelope<LiveSnapshot> & { type: 'laser.snapshot' }
  | LiveEnvelope<Measurement> & { type: 'laser.measurement' }
  | LiveEnvelope<SessionComplete> & { type: 'session.complete' }
  | LiveEnvelope<SerialStatus> & { type: 'laser.status' }
  | LiveEnvelope<ParseError> & { type: 'laser.parse_error' }
  | LiveEnvelope<null> & { type: 'pong' }

export interface LiveSnapshot {
  status: SerialStatus
  measurements: Measurement[]
  /** the backend includes these so a late-joining client needs no extra call */
  session?: SessionRecord | null
  parser?: ParserFieldsResponse
}

/** Emitted once per `OVER`: the batch that just closed. */
export interface SessionComplete {
  session_id: string
  record_count: number
  batch_seq: number
  raw_line_count?: number
  started_at?: string | null
  ended_at?: string | null
  port?: string | null
  status?: SessionStatus
}

export interface ParseError {
  line: string
  reason: string
}
