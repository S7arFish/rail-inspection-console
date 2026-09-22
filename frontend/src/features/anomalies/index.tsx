import { useMemo, useState } from 'react'
import { type ColumnDef } from '@tanstack/react-table'
import { useQuery } from '@tanstack/react-query'
import { Info } from 'lucide-react'
import { PageShell } from '@/components/layout/page-shell'
import { DataTable } from '@/components/console/data-table'
import { TonePill } from '@/components/console/tone-pill'
import { fetchReviewItems, USE_MOCK } from '@/lib/data-source'
import { dashboardMetrics } from '@/config/metrics'
import { formatDateTime, formatNumber } from '@/lib/format'
import { toneLabel, type Tone } from '@/lib/status'
import type { ReviewItem } from '@/types/console'

function useColumns(
  labelOf: (field: string) => string
): ColumnDef<ReviewItem, unknown>[] {
  return useMemo(
    () => [
      {
        accessorKey: 'ts',
        header: '时间',
        cell: ({ row }) => (
          <span className='readout text-[12px]'>
            {formatDateTime(row.original.ts)}
          </span>
        ),
      },
      {
        accessorKey: 'field',
        header: '指标',
        cell: ({ row }) => (
          <span className='grid leading-tight'>
            <span className='text-[12.5px]'>
              {labelOf(row.original.field)}
            </span>
            <span className='readout-id'>{row.original.field}</span>
          </span>
        ),
      },
      {
        accessorKey: 'value',
        header: '观测值',
        cell: ({ row }) => (
          <span className='readout text-[12.5px]'>
            {formatNumber(row.original.value)}
          </span>
        ),
      },
      {
        accessorKey: 'level',
        header: '判定',
        cell: ({ row }) => <TonePill tone={row.original.level as Tone} />,
      },
      {
        accessorKey: 'rule_label',
        header: '规则',
        cell: ({ cell }) => (
          <span className='text-[12px] text-muted-foreground'>
            {cell.getValue<string>()}
          </span>
        ),
      },
      {
        accessorKey: 'session_id',
        header: '会话',
        cell: ({ row }) => (
          <span className='readout-id'>{row.original.session_id}</span>
        ),
      },
    ],
    [labelOf]
  )
}

const levelOptions = [
  'nominal',
  'caution',
  'alarm',
  'unknown',
].map((value) => ({ value, label: toneLabel[value as Tone] }))

export function Anomalies() {
  const [focus, setFocus] = useState<ReviewItem | null>(null)
  const { data: items, isLoading } = useQuery({
    queryKey: ['review-items'],
    queryFn: fetchReviewItems,
  })

  const labelOf = useMemo(() => {
    const map = new Map(dashboardMetrics.map((m) => [m.field, m.label]))
    return (field: string) => map.get(field) ?? field
  }, [])

  const columns = useColumns(labelOf)

  return (
    <PageShell title='异常检测' subtitle='Anomaly review'>
      <div className='grid gap-3'>
        <div className='panel flex items-start gap-2.5 px-3.5 py-2.5'>
          <Info className='mt-0.5 size-4 shrink-0 text-muted-foreground' />
          <p className='text-[12px] leading-relaxed text-muted-foreground'>
            判定阈值与规则集尚未确认，后端当前不落库异常记录、前端也不内置任何阈值。
            {USE_MOCK ? ' 下列为演示数据，仅用于版面与交互评审。' : ''}
            字段名以{' '}
            <code className='readout text-[11.5px] text-foreground/80'>
              backend/config/parser.yaml
            </code>{' '}
            为准。
          </p>
        </div>

        <DataTable
          columns={columns}
          data={items ?? []}
          searchKey='field'
          searchPlaceholder='按字段名筛选…'
          filters={[{ columnId: 'level', title: '判定', options: levelOptions }]}
          emptyText={isLoading ? '加载中…' : '暂无待复核记录'}
          onRowClick={setFocus}
        />

        {focus ? (
          <div className='panel grid gap-1 px-3.5 py-2.5'>
            <span className='label-micro text-[10px]'>选中记录</span>
            <span className='readout text-[12.5px]'>{focus.id}</span>
            <p className='text-[12px] text-muted-foreground'>
              {focus.field} = {formatNumber(focus.value)} · {toneLabel[focus.level]} ·{' '}
              {focus.rule_label} ·{' '}
              {focus.synthetic ? '来源：演示数据' : '来源：后端'}
            </p>
          </div>
        ) : null}
      </div>
    </PageShell>
  )
}
