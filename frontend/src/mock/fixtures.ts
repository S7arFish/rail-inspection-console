import type {
  Measurement,
  ParserFieldsResponse,
  PortsResponse,
  SerialStatus,
  SessionRecord,
} from '@/types/domain'
import type { ReviewItem, TrackPoint } from '@/types/console'

/**
 * Fixtures for the mock build. Everything here is display scaffolding: the
 * numeric ranges are seeded from the single real sample line we have received
 * so the layout is reviewed against believable values. No detection limits,
 * tolerances or rule thresholds live here — none are confirmed yet.
 */

/** mulberry32: a deterministic stream keeps screenshots stable across reloads */
function seeded(seed: number) {
  let a = seed
  return () => {
    a |= 0
    a = (a + 0x6d2b79f5) | 0
    let t = Math.imul(a ^ (a >>> 15), 1 | a)
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

export const MOCK_SESSION_ID = 'MOCK-260922-091952'

/** Mirrors backend/config/parser.yaml; the real values come from /api/parser/fields. */
export const mockParserFields: ParserFieldsResponse = {
  fields: [
    { index: 0, name: 'record_type', type: 'int', unit: null, confirmed: true, note: '记录类型' },
    { index: 1, name: 'measure_direction', type: 'int', unit: null, confirmed: true, note: '测量方向' },
    { index: 2, name: 'record_no', type: 'int', unit: null, confirmed: true, note: '记录号' },
    { index: 3, name: 'line_no', type: 'int', unit: null, confirmed: true, note: '线号' },
    { index: 4, name: 'work_area', type: 'int', unit: null, confirmed: true, note: '工区' },
    { index: 5, name: 'pole_no', type: 'int', unit: null, confirmed: true, note: '杆号' },
    { index: 6, name: 'measure_position', type: 'int', unit: null, confirmed: true, note: '测量位置' },
    { index: 7, name: 'timestamp', type: 'timestamp', unit: null, confirmed: true, note: '时间，yyMMdd-HHmmss' },
    { index: 8, name: 'height', type: 'float', unit: null, confirmed: true, note: '高度，单位仪器未给出' },
    { index: 9, name: 'pull_out', type: 'float', unit: null, confirmed: true, note: '拉出，单位仪器未给出' },
    { index: 10, name: 'gauge', type: 'float', unit: null, confirmed: true, note: '轨距，单位仪器未给出' },
    {
      index: 11,
      name: 'metric_extra_1',
      type: 'float',
      unit: null,
      confirmed: false,
      note: '表头只有 11 列，此列含义未知，保持中性名，禁止猜测',
    },
  ],
  timestamp_field: 7,
  timestamp_format: '%y%m%d-%H%M%S',
  end_of_batch_token: 'OVER',
  expected_field_count: 12,
}

export const mockStatus: SerialStatus = {
  state: 'receiving',
  port: 'COM7',
  baud_rate: 115200,
  data_bits: 8,
  parity: 'N',
  stop_bits: 1,
  flow_control: 'none',
  session_id: MOCK_SESSION_ID,
  sample_count: 4820,
  batch_count: 241,
  records_in_batch: 6,
  last_line_at: new Date().toISOString(),
  last_error: null,
  rx_line_count: 5061,
  parse_error_count: 7,
  uptime_ms: 1000 * 60 * 42 + 1000 * 17,
}

/** Anchor values taken from the observed line `…,2121.5,582.2,1434.6,-9.8`. */
const ANCHOR = { height: 2121.5, pull_out: 582.2, gauge: 1434.6, extra: -9.8 }

/**
 * A trace, not a random walk: a long-wave profile plus small noise, which is
 * what a geometry channel actually looks like along a stretch of track. Keeps
 * the mock review honest about how the charts behave with real data.
 */
function trace(
  rand: () => number,
  base: number,
  amp: number,
  period: number,
  i: number,
  noise: number
) {
  return base + amp * Math.sin((i / period) * Math.PI * 2) + (rand() * 2 - 1) * noise
}

/** `260922-091952` = yyMMdd-HHmmss */
export function formatSerialTs(d: Date) {
  const p = (n: number) => String(n).padStart(2, '0')
  return `${p(d.getFullYear() % 100)}${p(d.getMonth() + 1)}${p(d.getDate())}-${p(d.getHours())}${p(d.getMinutes())}${p(d.getSeconds())}`
}

export function buildMeasurement(
  at: Date,
  rand: () => number,
  batchSeq: number,
  id: number,
  i: number
): Measurement {
  const height = trace(rand, ANCHOR.height, 58, 92, i, 1.1)
  const pullOut = trace(rand, ANCHOR.pull_out, 24, 61, i, 1.4)
  const gauge = trace(rand, ANCHOR.gauge, 3.2, 47, i, 0.35)
  const extra = trace(rand, ANCHOR.extra, 4.5, 73, i, 0.45)
  const tsRaw = formatSerialTs(at)
  return {
    id,
    session_id: MOCK_SESSION_ID,
    ts_raw: tsRaw,
    ts: at.toISOString(),
    fields: {
      record_type: 0,
      measure_direction: 0,
      record_no: i,
      line_no: 0,
      work_area: 0,
      pole_no: 1,
      measure_position: 1,
      height: Number(height.toFixed(1)),
      pull_out: Number(pullOut.toFixed(1)),
      gauge: Number(gauge.toFixed(1)),
      metric_extra_1: Number(extra.toFixed(1)),
    },
    raw_line: `0,0,0,0,0,1,1,${tsRaw},${height.toFixed(1)},${pullOut.toFixed(1)},${gauge.toFixed(1)},${extra.toFixed(1)}`,
    batch_seq: batchSeq,
    created_at: at.toISOString(),
  }
}

/** A finished stretch of samples, oldest first. */
export function mockMeasurements(count = 180): Measurement[] {
  const rand = seeded(20260922)
  const start = Date.parse('2026-09-22T09:19:52')
  return Array.from({ length: count }, (_, i) =>
    buildMeasurement(new Date(start + i * 1400), rand, Math.floor(i / 10) + 1, i + 1, i)
  )
}

/** Infinite live stream for the mock feed. */
export function createMockSampleStream() {
  const rand = seeded(Date.now() % 100000)
  let i = 0
  return () => {
    i += 1
    return buildMeasurement(
      new Date(),
      rand,
      Math.floor(i / 10) + 1,
      900000 + i,
      180 + i
    )
  }
}

/**
 * Enumeration is hardware-dependent, so the mock list mirrors what a real
 * CP210x-based inspection car shows on Windows — note `preferred` on the
 * Silicon Labs port, which is what `suggested_port` picks up.
 */
export const mockPorts: PortsResponse = {
  ports: [
    {
      device: 'COM7',
      name: 'COM7',
      description: 'Silicon Labs CP210x USB to UART Bridge (COM7)',
      hwid: 'USB VID:PID=10C4:EA60 SER=0001',
      preferred: true,
    },
    {
      device: 'COM3',
      name: 'COM3',
      description: 'Intel(R) Active Management Technology - SOL (COM3)',
      hwid: 'ACPI\\INTC0E9',
      preferred: false,
    },
  ],
  suggested_port: 'COM7',
  error: null,
}

export function mockSessions(): SessionRecord[] {
  const bases = [
    ['completed', 15840, 792, '线路A / 上行'],
    ['completed', 12210, 611, '线路A / 下行'],
    ['interrupted', 402, 21, '站内折返，链路中断'],
    ['completed', 18900, 945, '线路B / 上行'],
    ['failed', 0, 0, '串口未就绪，未能建立会话'],
    ['completed', 9120, 456, '线路C / 下行'],
    ['running', 4820, 241, '当前会话（演示）'],
  ] as const
  return bases.map(([status, sampleCount, batchCount, note], i) => {
    const started = Date.parse('2026-09-22T06:30:00') + i * 3600_000
    const runMs = sampleCount * 1400
    return {
      id: `S${formatSerialTs(new Date(started))}-${String(i + 1).padStart(2, '0')}`,
      started_at: new Date(started).toISOString(),
      ended_at: status === 'running' ? null : new Date(started + runMs).toISOString(),
      port: 'COM7',
      baud_rate: 115200,
      status,
      sample_count: sampleCount,
      batch_count: batchCount,
      source: 'serial',
      note: `${note} · 演示数据`,
    }
  })
}

/**
 * Placeholder review rows. `rule_label` is intentionally generic and `level`
 * stays `unknown` for most rows because no threshold set is configured —
 * do not read these as detection results.
 */
export function mockReviewItems(measurements: Measurement[]): ReviewItem[] {
  const rand = seeded(404)
  const fields = ['height', 'pull_out', 'gauge', 'metric_extra_1']
  return measurements
    .filter((_, i) => i % 23 === 7)
    .slice(0, 12)
    .map((m, i) => {
      const field = fields[Math.floor(rand() * fields.length)] ?? fields[0]
      const roll = rand()
      return {
        id: `R-${String(i + 1).padStart(3, '0')}`,
        session_id: m.session_id,
        ts: m.ts ?? m.created_at,
        field,
        value: (m.fields[field] as number) ?? null,
        rule_label: roll > 0.72 ? '待复核（演示）' : '未配置规则',
        level: roll > 0.86 ? 'alarm' : roll > 0.6 ? 'caution' : 'unknown',
        synthetic: true,
      }
    })
}

export function mockTrackPoints(measurements: Measurement[]): TrackPoint[] {
  return measurements
    .filter((_, i) => i % 3 === 0)
    .map((m, i) => ({
      position: 12480 + i * 4.2,
      ts: m.ts ?? m.created_at,
      level: i % 37 === 5 ? 'caution' : i % 53 === 9 ? 'alarm' : 'nominal',
      values: {
        height: m.fields.height as number,
        pull_out: m.fields.pull_out as number,
        gauge: m.fields.gauge as number,
        metric_extra_1: m.fields.metric_extra_1 as number,
      },
    }))
}
