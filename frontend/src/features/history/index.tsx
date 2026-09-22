import { useMemo } from 'react'
import { type ColumnDef } from '@tanstack/react-table'
import { useQuery } from '@tanstack/react-query'
import { PageShell } from '@/components/layout/page-shell'
import { DataTable } from '@/components/console/data-table'
import { TonePill } from '@/components/console/tone-pill'
import { fetchSessions } from '@/lib/data-source'
import { formatDateTime, formatInt } from '@/lib/format'
import type { Tone } from '@/lib/status'
import type { SessionRecord, SessionStatus } from '@/types/domain'

const statusTone: Record<SessionStatus, Tone> = {
  running: 'nominal',
  completed: 'idle',
  interrupted: 'caution',
  failed: 'alarm',
}

const statusLabel: Record<SessionStatus, string> = {
  running: '进行中',
  completed: '已完成',
  interrupted: '已中断',
  failed: '失败',
}

const columns: ColumnDef<SessionRecord, unknown>[] = [
  {
    accessorKey: 'id',
    header: '会话',
    cell: ({ row }) => (
      <span className='readout text-[12px]'>{row.original.id}</span>
    ),
  },
  {
    accessorKey: 'status',
    header: '状态',
    cell: ({ row }) => (
      <TonePill
        tone={statusTone[row.original.status]}
        label={statusLabel[row.original.status]}
      />
    ),
  },
  {
    accessorKey: 'started_at',
    header: '开始',
    cell: ({ row }) => (
      <span className='readout text-[12px]'>
        {formatDateTime(row.original.started_at)}
      </span>
    ),
  },
  {
    accessorKey: 'ended_at',
    header: '结束',
    cell: ({ row }) => (
      <span className='readout text-[12px] text-muted-foreground'>
        {formatDateTime(row.original.ended_at)}
      </span>
    ),
  },
  {
    accessorKey: 'port',
    header: '串口',
    cell: ({ row }) => (
      <span className='readout text-[12px]'>
        {row.original.port}
        <span className='text-muted-foreground'>
          {' '}
          · {row.original.baud_rate}
        </span>
      </span>
    ),
  },
  {
    accessorKey: 'sample_count',
    header: '样本',
    sortingFn: 'basic',
    cell: ({ row }) => (
      <span className='readout text-[12px]'>
        {formatInt(row.original.sample_count)}
      </span>
    ),
  },
  {
    accessorKey: 'batch_count',
    header: '批次',
    sortingFn: 'basic',
    cell: ({ row }) => (
      <span className='readout text-[12px] text-muted-foreground'>
        {formatInt(row.original.batch_count)}
      </span>
    ),
  },
  {
    accessorKey: 'note',
    header: '备注',
    cell: ({ row }) => (
      <span className='line-clamp-1 text-[12px] text-muted-foreground'>
        {row.original.note ?? '—'}
      </span>
    ),
  },
]

const statusOptions = (
  ['running', 'completed', 'interrupted', 'failed'] as SessionStatus[]
).map((value) => ({ value, label: statusLabel[value] }))

export function History() {
  const { data, isLoading } = useQuery({
    queryKey: ['sessions'],
    queryFn: () => fetchSessions(100, 0),
  })

  const rows = useMemo(
    () =>
      [...(data?.items ?? [])].sort(
        (a, b) => Date.parse(b.started_at) - Date.parse(a.started_at)
      ),
    [data]
  )

  return (
    <PageShell
      title='历史任务'
      subtitle='Inspection sessions'
      toolbar={
        <span className='hidden text-[11px] text-muted-foreground md:inline'>
          共 {data?.total ?? 0} 条
        </span>
      }
    >
      <DataTable
        columns={columns}
        data={rows}
        searchKey='id'
        searchPlaceholder='按会话号筛选…'
        filters={[
          { columnId: 'status', title: '状态', options: statusOptions },
        ]}
        emptyText={isLoading ? '加载中…' : '暂无历史会话'}
      />
      <p className='text-[11px] leading-relaxed text-muted-foreground'>
        会话与样本存放在本地 SQLite（<code className='readout'>data/</code>）。
        <code className='readout'>raw_lines</code> 表逐行保留原始串口文本，
        字段含义确认后可据此重放，无需重新采集。
      </p>
    </PageShell>
  )
}
