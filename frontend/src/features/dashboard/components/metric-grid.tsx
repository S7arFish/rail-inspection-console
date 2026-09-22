import { cn } from '@/lib/utils'
import { useParserFields } from '@/hooks/use-parser-fields'
import { dashboardMetrics, type MetricSlot } from '@/config/metrics'
import { formatNumber, formatSigned } from '@/lib/format'
import type { Measurement, ParserField } from '@/types/domain'

function Tile({
  slot,
  field,
  value,
  delta,
}: {
  slot: MetricSlot
  field: ParserField | undefined
  value: number | null
  delta: number | null
}) {
  const confirmed = field?.confirmed ?? false
  return (
    <div className='panel p-3.5'>
      <div className='flex items-center gap-2'>
        <span
          className={cn(
            'label-micro truncate',
            // a raw field name is a name, not a heading: leave its case alone
            slot.label === slot.field && 'normal-case'
          )}
        >
          {slot.label}
        </span>
        <span
          className={cn(
            'ms-auto shrink-0 rounded-sm border px-1 text-[10px] leading-4',
            confirmed
              ? 'border-signal-nominal/40 text-signal-nominal'
              : 'border-border text-muted-foreground'
          )}
          title={
            confirmed ? '字段含义已确认' : (field?.note ?? '字段含义待确认')
          }
        >
          {confirmed ? '已确认' : '暂定'}
        </span>
      </div>

      <div className='mt-2.5 flex items-end gap-1.5'>
        <span className='readout text-[28px] leading-none font-medium'>
          {formatNumber(value)}
        </span>
        <span className='pb-0.5 text-[11px] text-muted-foreground'>
          {field?.unit ?? '未定义单位'}
        </span>
      </div>

      <div className='mt-2.5 flex items-center justify-between border-t pt-2'>
        {/* the delta is a raw difference between two samples, not a judgement */}
        <span className='readout text-[11px] text-muted-foreground'>
          Δ {formatSigned(delta)}
        </span>
        <span className='readout-id truncate'>{slot.field}</span>
      </div>
    </div>
  )
}

function readNumber(m: Measurement | null, field: string) {
  const raw = m?.fields[field]
  if (raw === null || raw === undefined) return null
  const n = typeof raw === 'number' ? raw : Number.parseFloat(String(raw))
  return Number.isFinite(n) ? n : null
}

export function MetricGrid({
  latest,
  previous,
}: {
  latest: Measurement | null
  previous: Measurement | null
}) {
  const { data } = useParserFields()
  const fields = data?.fields ?? []

  return (
    <div className='grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4'>
      {dashboardMetrics.map((slot) => {
        const value = readNumber(latest, slot.field)
        const before = readNumber(previous, slot.field)
        return (
          <Tile
            key={slot.field}
            slot={slot}
            field={fields.find((f) => f.name === slot.field)}
            value={value}
            delta={value !== null && before !== null ? value - before : null}
          />
        )
      })}
    </div>
  )
}
