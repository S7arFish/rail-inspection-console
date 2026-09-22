import { useQuery } from '@tanstack/react-query'
import { Clock } from 'lucide-react'
import { fetchReviewItems, USE_MOCK } from '@/lib/data-source'
import { formatClock, formatNumber } from '@/lib/format'
import { Panel } from '@/components/console/panel'
import { TonePill } from '@/components/console/tone-pill'
import type { ReviewItem } from '@/types/console'

function Row({ item }: { item: ReviewItem }) {
  return (
    <li className='flex items-center gap-2 border-b py-1.5 last:border-b-0'>
      <span className='readout-id w-14 shrink-0'>{formatClock(item.ts)}</span>
      <span className='truncate text-[12px]'>{item.field}</span>
      <span className='readout ms-auto shrink-0 text-[12px]'>
        {formatNumber(item.value)}
      </span>
      <TonePill tone={item.level} className='shrink-0 border-0 px-0' />
    </li>
  )
}

/**
 * Recent review items. With no rule catalogue configured, `level` stays
 * `unknown` for most rows — that is the honest state, not a defect.
 */
export function ReviewList({ limit = 8 }: { limit?: number }) {
  const { data, isLoading } = useQuery({
    queryKey: ['review-items'],
    queryFn: fetchReviewItems,
  })
  const items = (data ?? []).slice(0, limit)

  return (
    <Panel
      eyebrow='待复核'
      title='最近异常'
      bodyClassName='px-3.5 py-1.5'
      actions={
        <span className='inline-flex items-center gap-1 text-[11px] text-muted-foreground'>
          <Clock className='size-3.5' /> {items.length}
        </span>
      }
    >
      {isLoading ? (
        <p className='py-6 text-center text-[12px] text-muted-foreground'>
          加载中…
        </p>
      ) : items.length === 0 ? (
        <p className='py-6 text-center text-[12px] text-muted-foreground'>
          {USE_MOCK ? '暂无记录' : '检测标准未配置，暂无判定结果'}
        </p>
      ) : (
        <ul>
          {items.map((item) => (
            <Row key={item.id} item={item} />
          ))}
        </ul>
      )}
      <p className='border-t px-0.5 py-2 text-[10.5px] leading-relaxed text-muted-foreground'>
        阈值配置为空，未启用任何判定规则。
        {USE_MOCK ? ' 当前列表为演示数据，不代表检测结果。' : ''}
      </p>
    </Panel>
  )
}
