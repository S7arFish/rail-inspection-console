import { WifiOff } from 'lucide-react'
import { cn } from '@/lib/utils'
import { useLiveFeedContext } from '@/context/live-feed-provider'
import {
  LINK_UP_STATES,
  serialStateLabel,
  serialStateTone,
  toneDot,
} from '@/lib/status'
import { formatClock, formatDuration, formatInt } from '@/lib/format'

function Cell({
  label,
  value,
  className,
  title,
}: {
  label: string
  value: string
  className?: string
  title?: string
}) {
  return (
    <div className={cn('grid min-w-0 leading-tight', className)} title={title}>
      <span className='text-[10px] tracking-[0.12em] text-muted-foreground uppercase'>
        {label}
      </span>
      <span className='readout truncate text-[13px]'>{value}</span>
    </div>
  )
}

const Divider = () => (
  <span className='hidden h-8 w-px bg-border lg:block' aria-hidden='true' />
)

/** Device / link status — the gate every other panel depends on. */
export function LinkBanner() {
  const { status, streaming, mocked } = useLiveFeedContext()
  const state = status?.state ?? 'disconnected'
  const tone = serialStateTone[state]

  return (
    <div className='panel flex flex-wrap items-center gap-x-5 gap-y-3 px-4 py-2.5'>
      <div className='flex items-center gap-2.5'>
        <span
          className={cn(
            'size-2 shrink-0 rounded-full',
            toneDot[tone],
            LINK_UP_STATES.includes(state) && streaming && 'live-dot'
          )}
          aria-hidden='true'
        />
        <div className='grid leading-tight'>
          <span className='text-[13px] font-medium'>
            设备连接 · {serialStateLabel[state]}
          </span>
          <span className='readout-id'>
            {status?.port ?? '无活动端口'} ·{' '}
            {status?.baud_rate
              ? `${status.baud_rate} ${status.data_bits ?? 8}${status.parity ?? 'N'}${status.stop_bits ?? 1}`
              : '未配置波特率'}
            {status?.flow_control && status.flow_control !== 'none'
              ? ` ${status.flow_control}`
              : ' 无流控'}
          </span>
        </div>
      </div>

      <Divider />

      <Cell label='会话' value={status?.session_id ?? '—'} className='min-w-32' />
      <Cell
        label='本批'
        value={
          state === 'receiving'
            ? `${status?.records_in_batch ?? 0} 条`
            : status?.batch_count
              ? `${status.batch_count} 批已完成`
              : '等待导出'
        }
      />
      <Cell label='样本' value={formatInt(status?.sample_count)} />
      <Cell label='批次' value={formatInt(status?.batch_count)} />
      <Cell label='链路时长' value={formatDuration(status?.uptime_ms)} />
      <Cell
        label='解析错误'
        value={formatInt(status?.parse_error_count)}
        className={cn(
          (status?.parse_error_count ?? 0) > 0 && 'text-signal-caution'
        )}
      />

      <div className='ms-auto flex items-center gap-2.5'>
        {status?.last_error ? (
          <span
            className='max-w-56 truncate text-[11px] text-signal-alarm'
            title={status.last_error}
          >
            {status.last_error}
          </span>
        ) : null}
        {streaming ? (
          <span className='label-micro text-[10px] text-muted-foreground'>
            末行 {formatClock(status?.last_line_at)}
          </span>
        ) : (
          <span className='inline-flex items-center gap-1.5 text-[11px] text-muted-foreground'>
            <WifiOff className='size-3.5' /> 数据通道未就绪
          </span>
        )}
        {mocked ? (
          <span
            className='rounded-sm border border-signal-caution/45 px-1.5 py-0.5 text-[10px] text-signal-caution'
            title='VITE_USE_MOCK=true：当前为前端演示数据，未经过串口'
          >
            演示数据
          </span>
        ) : null}
      </div>
    </div>
  )
}
