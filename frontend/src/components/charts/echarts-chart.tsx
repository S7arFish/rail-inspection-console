import { useEffect, useRef } from 'react'
import { echarts, type ChartOption, type EChartsType } from '@/lib/echarts'
import { cn } from '@/lib/utils'

type EChartsChartProps = {
  option: ChartOption
  className?: string
  /** replace instead of merge — set false when animating a growing series */
  notMerge?: boolean
  ariaLabel?: string
}

export function EChartsChart({
  option,
  className,
  notMerge = true,
  ariaLabel,
}: EChartsChartProps) {
  const hostRef = useRef<HTMLDivElement>(null)
  const instanceRef = useRef<EChartsType | null>(null)

  useEffect(() => {
    const host = hostRef.current
    if (!host) return

    const chart = echarts.init(host, undefined, { renderer: 'canvas' })
    instanceRef.current = chart

    // Density here is line-level, so keep the redraw cheap and unthrottled.
    const observer = new ResizeObserver(() => chart.resize())
    observer.observe(host)

    return () => {
      observer.disconnect()
      chart.dispose()
      instanceRef.current = null
    }
  }, [])

  useEffect(() => {
    instanceRef.current?.setOption(option, { notMerge, lazyUpdate: true })
  }, [option, notMerge])

  return (
    <div
      ref={hostRef}
      role='img'
      aria-label={ariaLabel}
      className={cn('w-full', className)}
    />
  )
}
