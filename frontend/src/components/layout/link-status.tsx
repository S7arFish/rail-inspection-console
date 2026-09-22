import { Cable, Unplug } from 'lucide-react'
import { cn } from '@/lib/utils'
import { useLiveFeedContext } from '@/context/live-feed-provider'
import {
  LINK_UP_STATES,
  serialStateLabel,
  serialStateTone,
  toneDot,
} from '@/lib/status'
import { Button } from '@/components/ui/button'
import { SidebarGroup } from '@/components/ui/sidebar'

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className='flex items-baseline justify-between gap-3'>
      <span className='text-[10.5px] tracking-wide text-muted-foreground'>
        {label}
      </span>
      <span className='readout text-[11.5px] text-foreground/90'>{value}</span>
    </div>
  )
}

/** Serial link summary — always visible, since it gates every other panel. */
export function LinkStatus() {
  const { status, streaming, mocked, pending, connect, disconnect } =
    useLiveFeedContext()

  const state = status?.state ?? 'disconnected'
  const tone = serialStateTone[state]
  const up = LINK_UP_STATES.includes(state)

  return (
    <SidebarGroup className='p-2'>
      <div className='rounded-md border border-sidebar-border bg-sidebar-accent/40 p-2.5'>
        <div className='mb-2 flex items-center gap-2'>
          <span
            className={cn(
              'size-1.5 shrink-0 rounded-full',
              toneDot[tone],
              up && streaming && 'live-dot'
            )}
            aria-hidden='true'
          />
          <span className='text-[12px] font-medium'>
            {serialStateLabel[state]}
          </span>
          <span className='readout-id ms-auto'>{status?.port ?? '—'}</span>
        </div>

        <div className='grid gap-1'>
          {up ? (
            <Row
              label={state === 'receiving' ? '本批已接收' : '已完成批次'}
              value={
                state === 'receiving'
                  ? `${status?.records_in_batch ?? 0} 条`
                  : `${status?.batch_count ?? 0}`
              }
            />
          ) : null}
          <Row
            label='线路参数'
            value={
              status?.baud_rate
                ? `${status.baud_rate} ${status.data_bits ?? 8}${status.parity ?? 'N'}${status.stop_bits ?? 1}`
                : '未配置'
            }
          />
          <Row label='样本' value={(status?.sample_count ?? 0).toLocaleString()} />
        </div>

        {mocked ? (
          <p className='mt-2 border-t border-sidebar-border pt-2 text-[10.5px] leading-relaxed text-muted-foreground'>
            演示数据 · 未接入串口
          </p>
        ) : (
          <Button
            size='sm'
            variant={up ? 'outline' : 'secondary'}
            className='mt-2.5 w-full'
            disabled={pending !== null}
            onClick={() => (up ? void disconnect() : void connect())}
          >
            {up ? <Unplug /> : <Cable />}
            {pending === 'disconnect'
              ? '断开中…'
              : pending === 'connect'
                ? '连接中…'
                : up
                  ? '断开链路'
                  : '建立链路'}
          </Button>
        )}
      </div>
    </SidebarGroup>
  )
}
