import { useMemo } from 'react'
import { cn } from '@/lib/utils'
import { USE_MOCK } from '@/lib/data-source'
import { toneDot } from '@/lib/status'
import { formatClock, formatNumber } from '@/lib/format'
import { Panel } from '@/components/console/panel'
import type { TrackPoint } from '@/types/console'

const LEGEND = [
  { key: 'nominal', label: '正常段' },
  { key: 'caution', label: '注意段' },
  { key: 'alarm', label: '报警段' },
  { key: 'unknown', label: '未判定' },
] as const

function scaleMarks(count: number) {
  return [0, 0.25, 0.5, 0.75, 1].map((ratio) => ({
    ratio,
    index: Math.min(count - 1, Math.round(ratio * (count - 1))),
  }))
}

/**
 * Position strip: one mark per received sample, laid out along the stretch.
 * Colour follows the (still unconfigured) judgement of each point, so most
 * marks sit in the neutral tone by design.
 */
export function TrackStrip({
  points,
  selected,
  onSelect,
}: {
  points: TrackPoint[]
  selected: number | null
  onSelect: (index: number) => void
}) {
  const marks = useMemo(() => scaleMarks(points.length || 1), [points.length])
  const current = points.length ? points[points.length - 1] : null
  // Judgement colours only exist in the mock build; see README (no thresholds).
  const judged = USE_MOCK

  return (
    <Panel
      eyebrow='线路状态'
      title='点位条 / 时间轴'
      bodyClassName='pt-3 pb-2.5'
      actions={
        judged ? (
          <div className='flex items-center gap-3'>
            {LEGEND.map((l) => (
              <span
                key={l.key}
                className='flex items-center gap-1.5 text-[11px] text-muted-foreground'
              >
                <span className={cn('size-1.5 rounded-full', toneDot[l.key])} />
                {l.label}
              </span>
            ))}
          </div>
        ) : (
          // No thresholds exist yet, so no point may be drawn as 正常/异常.
          <span className='text-[11px] text-muted-foreground'>
            检测标准未配置 · 仅显示点位
          </span>
        )
      }
    >
      {points.length === 0 ? (
        <p className='py-6 text-center text-[12px] text-muted-foreground'>
          暂无点位数据
        </p>
      ) : (
        <>
          <div className='track-ticks relative h-9 w-full overflow-hidden rounded-sm'>
            {points.map((p, i) => (
              <button
                key={`${p.ts}-${i}`}
                type='button'
                onClick={() => onSelect(i)}
                aria-label={`点位 ${i + 1}`}
                title={`${formatClock(p.ts)} · ${formatNumber(p.position, 1)}${judged ? ` · ${p.level}` : ''}`}
                className={cn(
                  'absolute inset-y-0 w-[3px] -translate-x-1/2 rounded-[1px] transition-opacity',
                  toneDot[judged ? p.level : 'unknown'],
                  selected === i
                    ? 'opacity-100 ring-1 ring-foreground/60'
                    : 'opacity-70 hover:opacity-100'
                )}
                style={{ left: `${(i / (points.length - 1 || 1)) * 100}%` }}
              />
            ))}
            {/* head of the run: where the car is reading now */}
            <span
              className='absolute inset-y-0 -translate-x-1/2 border-s border-foreground/50'
              style={{ left: '100%' }}
              aria-hidden='true'
            />
          </div>

          <div className='mt-1.5 flex items-center justify-between'>
            {marks.map((m) => (
              <span key={m.ratio} className='readout-id text-[10px]'>
                {formatNumber(points[m.index]?.position, 0)}
              </span>
            ))}
          </div>

          <div className='mt-2 flex flex-wrap items-center gap-x-5 gap-y-1 border-t pt-2 text-[11px] text-muted-foreground'>
            <span>
              点位 <span className='readout text-foreground'>{points.length}</span>
            </span>
            <span>
              当前{' '}
              <span className='readout text-foreground'>
                {formatNumber(current?.position, 1)}
              </span>
            </span>
            {selected !== null && points[selected] ? (
              <span className='ms-auto'>
                选中 #{selected + 1} ·{' '}
                <span className='readout'>
                  {formatClock(points[selected].ts)}
                </span>{' '}
                ·{' '}
                {Object.entries(points[selected].values)
                  .map(([k, v]) => `${k} ${formatNumber(v)}`)
                  .join('  ')}
              </span>
            ) : (
              <span className='ms-auto'>点击色块查看点位</span>
            )}
          </div>
        </>
      )}
    </Panel>
  )
}
