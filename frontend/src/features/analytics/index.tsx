import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { EChartsChart } from '@/components/charts/echarts-chart'
import { PageShell } from '@/components/layout/page-shell'
import { Panel } from '@/components/console/panel'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { axisDefaults, baseChartOptions, useChartPalette } from '@/lib/chart-theme'
import { type ChartOption } from '@/lib/echarts'
import { dashboardMetrics, secondaryAxisFields } from '@/config/metrics'
import { fetchMeasurements, fetchSessions } from '@/lib/data-source'
import { formatNumber } from '@/lib/format'

function stats(values: (number | null)[]) {
  const nums = values.filter((v): v is number => typeof v === 'number')
  if (nums.length === 0)
    return { n: 0, min: null, max: null, mean: null, range: null }
  const min = Math.min(...nums)
  const max = Math.max(...nums)
  const mean = nums.reduce((a, b) => a + b, 0) / nums.length
  return { n: nums.length, min, max, mean, range: max - min }
}

export function Analytics() {
  const palette = useChartPalette()
  const [sessionId, setSessionId] = useState<string | null>(null)

  const sessions = useQuery({
    queryKey: ['sessions'],
    queryFn: () => fetchSessions(100, 0),
  })
  const { data: samples, isLoading } = useQuery({
    queryKey: ['measurements', sessionId],
    queryFn: () => fetchMeasurements(sessionId ?? undefined),
  })

  const rows = useMemo(() => samples ?? [], [samples])

  const summary = useMemo(
    () =>
      dashboardMetrics.map((slot) => ({
        slot,
        ...stats(
          rows.map((m) => {
            const raw = m.fields[slot.field]
            const n = typeof raw === 'number' ? raw : Number.parseFloat(String(raw))
            return Number.isFinite(n) ? n : null
          })
        ),
      })),
    [rows]
  )

  const option = useMemo<ChartOption>(() => {
    const axis = axisDefaults(palette)
    const secondary = new Set(secondaryAxisFields)
    return {
      ...baseChartOptions(palette),
      legend: {
        top: 0,
        right: 0,
        icon: 'rect',
        itemWidth: 10,
        itemHeight: 2,
        textStyle: { color: palette.text, fontSize: 11 },
      },
      grid: { left: 6, right: 12, top: 28, bottom: 44, containLabel: true },
      dataZoom: [
        { type: 'inside', throttle: 60 },
        {
          type: 'slider',
          height: 18,
          bottom: 6,
          borderColor: palette.axisLine,
          fillerColor: palette.isDark
            ? 'rgba(255,255,255,.06)'
            : 'rgba(0,0,0,.05)',
          handleStyle: { color: palette.text },
          textStyle: { color: palette.text, fontSize: 10 },
        },
      ],
      xAxis: {
        type: 'category',
        boundaryGap: false,
        data: rows.map((m) => m.ts_raw ?? String(m.id)),
        ...axis,
        splitLine: { show: false },
      },
      yAxis: [
        { type: 'value', scale: true, ...axis },
        {
          type: 'value',
          scale: true,
          position: 'right',
          ...axis,
          splitLine: { show: false },
        },
      ],
      series: dashboardMetrics.map((slot) => ({
        name: slot.label,
        type: 'line' as const,
        yAxisIndex: secondary.has(slot.field) ? 1 : 0,
        showSymbol: false,
        lineStyle: { width: 1.2, color: palette.series[slot.series] },
        itemStyle: { color: palette.series[slot.series] },
        areaStyle: undefined,
        data: rows.map((m) => {
          const raw = m.fields[slot.field]
          const n = typeof raw === 'number' ? raw : Number.parseFloat(String(raw))
          return Number.isFinite(n) ? n : null
        }),
      })),
    }
  }, [rows, palette])

  return (
    <PageShell
      title='数据分析'
      subtitle='Session analysis'
      toolbar={
        <Select
          value={sessionId ?? '__latest'}
          onValueChange={(v) => setSessionId(v === '__latest' ? null : v)}
        >
          <SelectTrigger size='sm' className='w-56'>
            <SelectValue placeholder='选择会话' />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value='__latest'>最近会话（演示）</SelectItem>
            {(sessions.data?.items ?? []).map((s) => (
              <SelectItem key={s.id} value={s.id}>
                {s.id}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      }
    >
      <div className='grid gap-3'>
        <Panel
          eyebrow='统计'
          title={`指标描述统计 · ${rows.length} 条样本`}
          bodyClassName='p-0'
        >
          <Table>
            <TableHeader className='bg-muted/40'>
              <TableRow>
                {['指标', '字段', '样本', '最小', '均值', '最大', '极差'].map(
                  (h) => (
                    <TableHead key={h}>{h}</TableHead>
                  )
                )}
              </TableRow>
            </TableHeader>
            <TableBody>
              {summary.map((r) => (
                <TableRow key={r.slot.field}>
                  <TableCell className='text-[12.5px]'>{r.slot.label}</TableCell>
                  <TableCell>
                    <span className='readout-id'>{r.slot.field}</span>
                  </TableCell>
                  <TableCell>
                    <span className='readout text-[12px]'>{r.n}</span>
                  </TableCell>
                  <TableCell>
                    <span className='readout text-[12px]'>
                      {formatNumber(r.min)}
                    </span>
                  </TableCell>
                  <TableCell>
                    <span className='readout text-[12px]'>
                      {formatNumber(r.mean)}
                    </span>
                  </TableCell>
                  <TableCell>
                    <span className='readout text-[12px]'>
                      {formatNumber(r.max)}
                    </span>
                  </TableCell>
                  <TableCell>
                    <span className='readout text-[12px] text-muted-foreground'>
                      {formatNumber(r.range)}
                    </span>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </Panel>

        <Panel
          eyebrow='序列'
          title='全量序列总览（可缩放）'
          bodyClassName='p-1.5'
          actions={
            <span className='label-micro text-[10px]'>
              滚轮或下方滑块缩放
            </span>
          }
        >
          <EChartsChart
            option={option}
            className='h-72'
            ariaLabel='全量指标序列图'
          />
          {isLoading ? (
            <p className='pb-2 text-center text-[11px] text-muted-foreground'>
              加载中…
            </p>
          ) : null}
        </Panel>
      </div>
    </PageShell>
  )
}
