import { useMemo } from 'react'
import { cn } from '@/lib/utils'
import { useLiveFeedContext } from '@/context/live-feed-provider'
import { formatClock } from '@/lib/format'
import { Panel } from '@/components/console/panel'

type TapLine = {
  key: string
  kind: 'data' | 'control' | 'invalid'
  text: string
  at: string | null
}

const kindClass: Record<TapLine['kind'], string> = {
  data: 'text-foreground/85',
  control: 'text-signal-caution',
  invalid: 'text-signal-alarm',
}

const kindTag: Record<TapLine['kind'], string> = {
  data: 'RX',
  control: 'EOB',
  invalid: 'ERR',
}

/**
 * Raw tap: the physical lines exactly as they arrived, newest first. Kept on
 * purpose while the field table is still being confirmed — the parsed values
 * above are derived from these.
 */
export function RawTap({ rows = 9 }: { rows?: number }) {
  const { samples, lastBatch, recentErrors } = useLiveFeedContext()

  const lines = useMemo<TapLine[]>(() => {
    const data: TapLine[] = samples
      .slice(-rows)
      .map((m, i) => ({
        key: `d-${m.id}-${i}`,
        kind: 'data' as const,
        text: m.raw_line,
        at: m.ts ?? m.created_at,
      }))
      .reverse()

    const extras: TapLine[] = [
      ...(lastBatch
        ? [
            {
              key: `c-${lastBatch.batch_seq}`,
              kind: 'control' as const,
              text: `OVER — 批次 ${lastBatch.batch_seq} 结束，共 ${lastBatch.record_count} 条`,
              at: null,
            },
          ]
        : []),
      ...recentErrors.slice(0, 3).map((e, i) => ({
        key: `e-${i}-${e.line}`,
        kind: 'invalid' as const,
        text: `${e.line}  ⟵ ${e.reason}`,
        at: null,
      })),
    ]

    return [...extras, ...data].slice(0, rows)
  }, [samples, lastBatch, recentErrors, rows])

  return (
    <Panel
      eyebrow='原始行'
      title='串口原始数据保留'
      bodyClassName='p-0'
      actions={
        <span className='label-micro text-[10px]'>EOB = 批次结束标记</span>
      }
    >
      <div className='max-h-56 overflow-y-auto px-3.5 py-2'>
        {lines.length === 0 ? (
          <p className='py-6 text-center text-[12px] text-muted-foreground'>
            尚未收到数据行
          </p>
        ) : (
          <table className='w-full border-separate border-spacing-0'>
            <tbody>
              {lines.map((l) => (
                <tr key={l.key} className='align-baseline'>
                  <td className='w-10 py-[3px] pe-2'>
                    <span
                      className={cn(
                        'readout text-[10px] tracking-wide',
                        kindClass[l.kind]
                      )}
                    >
                      {kindTag[l.kind]}
                    </span>
                  </td>
                  <td className='w-16 py-[3px] pe-3'>
                    <span className='readout-id text-[10.5px]'>
                      {formatClock(l.at)}
                    </span>
                  </td>
                  <td
                    className={cn(
                      'readout truncate py-[3px] text-[11.5px]',
                      kindClass[l.kind]
                    )}
                  >
                    {l.text}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </Panel>
  )
}
