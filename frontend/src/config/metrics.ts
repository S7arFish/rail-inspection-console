/**
 * The only place a parser field name is bound to a display label.
 * Names come from `backend/config/parser.yaml`; nothing here implies a limit,
 * a unit or a judgement — those are still unconfirmed.
 */
export type MetricSlot = {
  field: string
  label: string
  /** shown as `暂定` so an operator knows the mapping is provisional */
  tentative?: boolean
  /** index into the chart series palette, stable across pages */
  series: number
}

export const dashboardMetrics: MetricSlot[] = [
  { field: 'height', label: '当前高度', tentative: true, series: 0 },
  { field: 'pull_out', label: '当前拉出值', tentative: true, series: 1 },
  { field: 'gauge', label: '当前轨距', tentative: true, series: 2 },
  { field: 'metric_extra_1', label: 'metric_extra_1', tentative: true, series: 3 },
]

/** Series plotted against the secondary axis (different order of magnitude). */
export const secondaryAxisFields = ['metric_extra_1']
