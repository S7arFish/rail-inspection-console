import type { Measurement } from './domain'

/**
 * Shapes the backend does not expose yet. The 异常检测 / 数据分析 pages read
 * these from fixtures in this phase; swap `src/lib/data-source.ts` when the
 * API grows to cover them.
 */

/** `unknown` is the honest default while no rule engine exists. */
export type ReviewLevel = 'nominal' | 'caution' | 'alarm' | 'unknown'

export interface ReviewItem {
  id: string
  session_id: string
  ts: string
  /** configured parser field name, e.g. `metric_extra_1` */
  field: string
  value: number | null
  /** placeholder label — no rule catalogue is defined on purpose */
  rule_label: string
  level: ReviewLevel
  /** true when the row came from fixtures, not from the console */
  synthetic: boolean
}

export interface TrackPoint {
  /** position along the inspected stretch; unit follows the parser config */
  position: number
  ts: string
  level: ReviewLevel
  values: Record<string, number | null>
}

export interface DashboardSnapshot {
  measurements: Measurement[]
  latest: Measurement | null
}
