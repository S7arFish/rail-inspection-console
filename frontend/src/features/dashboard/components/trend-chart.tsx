import { useMemo } from 'react'
import { EChartsChart } from '@/components/charts/echarts-chart'
import { Panel } from '@/components/console/panel'
import { axisDefaults, baseChartOptions, useChartPalette } from '@/lib/chart-theme'
import { dashboardMetrics, secondaryAxisFields } from '@/config/metrics'
import { formatClock } from '@/lib/format'
import { type ChartOption } from '@/lib/echarts'
import type { Measurement } from '@/types/domain'

function numeric(m: Measurement, field: string) {
  const raw = m.fields[field]
  if (raw === null || raw === undefined) return null
  const n = typeof raw === 'number' ? raw : Number.parseFloat(String(raw))
  return Number.isFinite(n) ? n : null
}

/**
 * Multi-metric trend. Series colours come from `--chart-n` via the slot config
 * so a metric keeps the same colour everywhere in the console.
 */
export function TrendChart({
  samples,
  windowSize = 120,
}: {
  samples: Measurement[]
  windowSize?: number
}) {
  const palette = useChartPalette()

  const option = useMemo<ChartOption>(() => {
    const view = samples.slice(-windowSize)
    const axis = axisDefaults(palette)
    const secondary = new Set(secondaryAxisFields)

    return {
      ...baseChartOptions(palette),
      legend: {
        top: 0,
        right: 0,
        itemWidth: 10,
        itemHeight: 2,
        icon: 'rect',
        textStyle: { color: palette.text, fontSize: 11 },
      },
      grid: { left: 6, right: secondary.size ? 6 : 12, top: 26, bottom: 4, containLabel: true },
      xAxis: {
        type: 'category',
        boundaryGap: false,
        data: view.map((m) => formatClock(m.ts ?? m.created_at)),
        ...axis,
        splitLine: { show: false },
      },
      yAxis: [
        {
          type: 'value',
          scale: true,
          ...axis,
          axisLabel: { ...axis.axisLabel, formatter: (v: number) => `${v}` },
        },
        {
          type: 'value',
          scale: true,
          ...axis,
          position: 'right',
          show: secondary.size > 0,
          splitLine: { show: false },
        },
      ],
      series: dashboardMetrics.map((slot) => ({
        name: slot.label,
        type: 'line' as const,
        yAxisIndex: secondary.has(slot.field) ? 1 : 0,
        showSymbol: false,
        symbol: 'circle' as const,
        symbolSize: 4,
        smooth: false,
        lineStyle: { width: 1.4, color: palette.series[slot.series] },
        itemStyle: { color: palette.series[slot.series] },
        emphasis: { focus: 'series' as const },
        data: view.map((m) => numeric(m, slot.field)),
      })),
    }
  }, [samples, windowSize, palette])

  return (
    <Panel
      eyebrow='趋势'
      title={`最近 ${Math.min(windowSize, samples.length) || 0} 个样本`}
      actions={
        <span className='label-micro text-[10px]'>
          {secondaryAxisFields.length
            ? `${secondaryAxisFields.join(', ')} → 右轴`
            : null}
        </span>
      }
      bodyClassName='p-1.5'
    >
      <EChartsChart
        option={option}
        className='h-56 xl:h-64'
        ariaLabel='多指标趋势图'
      />
    </Panel>
  )
}
