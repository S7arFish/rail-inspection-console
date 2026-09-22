import { useEffect, useMemo, useState } from 'react'

function readVar(name: string, fallback: string) {
  const value = getComputedStyle(document.documentElement)
    .getPropertyValue(name)
    .trim()
  return value || fallback
}

/**
 * ECharts cannot resolve CSS custom properties, so palette values are read off
 * the live document and the chart re-renders when the theme class flips.
 */
export function useChartPalette() {
  const [isDark, setIsDark] = useState(
    () => document.documentElement.classList.contains('dark')
  )

  useEffect(() => {
    const observer = new MutationObserver(() =>
      setIsDark(document.documentElement.classList.contains('dark'))
    )
    observer.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ['class'],
    })
    return () => observer.disconnect()
  }, [])

  return useMemo(
    () => ({
      isDark,
      text: readVar('--muted-foreground', '#8b8b8b'),
      strongText: readVar('--foreground', '#e8e8e8'),
      axisLine: readVar('--border', 'rgba(255,255,255,.12)'),
      splitLine: isDark ? 'rgba(255,255,255,.06)' : 'rgba(0,0,0,.07)',
      surface: readVar('--popover', '#1b1b1b'),
      series: [
        readVar('--chart-1', '#d99a3d'),
        readVar('--chart-2', '#4aa891'),
        readVar('--chart-3', '#8f7fc0'),
        readVar('--chart-4', '#c2605f'),
        readVar('--chart-5', '#7ba05b'),
      ],
      nominal: readVar('--signal-nominal', '#4a9c6d'),
      caution: readVar('--signal-caution', '#d9a13d'),
      alarm: readVar('--signal-alarm', '#c8504a'),
      idle: readVar('--signal-idle', '#7a7a7a'),
    }),
    [isDark]
  )
}

export type ChartPalette = ReturnType<typeof useChartPalette>

/** Shared axis/frame so every panel in the console reads as one instrument. */
export function baseChartOptions(p: ChartPalette) {
  return {
    animationDuration: 320,
    animationEasing: 'cubicOut' as const,
    textStyle: {
      fontFamily: "'JetBrains Mono', ui-monospace, monospace",
      fontSize: 11,
      color: p.text,
    },
    grid: {
      left: 8,
      right: 12,
      top: 18,
      bottom: 8,
      containLabel: true,
    },
    tooltip: {
      trigger: 'axis' as const,
      backgroundColor: p.surface,
      borderColor: p.axisLine,
      borderWidth: 1,
      padding: [6, 9] as [number, number],
      extraCssText: 'border-radius:4px;box-shadow:none;',
      textStyle: { color: p.strongText, fontSize: 11 },
      axisPointer: {
        type: 'line' as const,
        lineStyle: { color: p.axisLine, width: 1, type: 'solid' as const },
        snap: true,
      },
    },
  }
}

export function axisDefaults(p: ChartPalette) {
  return {
    axisLine: { lineStyle: { color: p.axisLine } },
    axisTick: { show: false },
    axisLabel: { color: p.text, fontSize: 10.5, hideOverlap: true },
    splitLine: { show: true, lineStyle: { color: p.splitLine, width: 1 } },
  }
}

export const SERIES_LINE = {
  showSymbol: false,
  symbol: 'rect' as const,
  symbolSize: 5,
  lineWidth: 1.5,
  smooth: false,
}
