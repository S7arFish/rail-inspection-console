import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Cable, CircleCheck, RefreshCw, Unplug } from 'lucide-react'
import { toast } from 'sonner'
import { PageShell } from '@/components/layout/page-shell'
import { Panel } from '@/components/console/panel'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Separator } from '@/components/ui/separator'
import { Skeleton } from '@/components/ui/skeleton'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { useLayout } from '@/context/layout-provider'
import { useLiveFeedContext } from '@/context/live-feed-provider'
import { useTheme } from '@/context/theme-provider'
import { useFont } from '@/context/font-provider'
import { fonts } from '@/config/fonts'
import { fetchPorts, USE_MOCK } from '@/lib/data-source'
import { cn } from '@/lib/utils'
import {
  serialStateLabel,
  serialStateTone,
  toneDot,
} from '@/lib/status'
import { useParserFields } from '@/hooks/use-parser-fields'
import { formatInt } from '@/lib/format'

/** Defaults match the backend: COM7 / 115200 / 8 / N / 1 / no flow control. */
const BAUD_RATES = ['9600', '19200', '38400', '57600', '115200', '230400']
const PARITIES = [
  { value: 'N', label: '无 (None)' },
  { value: 'E', label: '偶 (Even)' },
  { value: 'O', label: '奇 (Odd)' },
]
const FLOW = [
  { value: 'none', label: '无流控' },
  { value: 'hardware', label: 'RTS/CTS' },
  { value: 'software', label: 'XON/XOFF' },
]

function Field({
  label,
  hint,
  children,
}: {
  label: string
  hint?: string
  children: React.ReactNode
}) {
  return (
    <div className='grid min-w-0 gap-1.5'>
      <Label className='label-micro text-[10px]'>{label}</Label>
      {children}
      {hint ? (
        <span className='text-[11px] text-muted-foreground'>{hint}</span>
      ) : null}
    </div>
  )
}

export function Settings() {
  const { status, connect, disconnect, pending, error, lastBatch } =
    useLiveFeedContext()
  const state = status?.state ?? 'disconnected'
  const { theme, setTheme } = useTheme()
  const { font, setFont } = useFont()
  const { variant, setVariant } = useLayout()

  const ports = useQuery({
    queryKey: ['serial', 'ports'],
    queryFn: fetchPorts,
    staleTime: 30_000,
  })

  // Defaults follow the live link, then the suggested (CP210x / Silicon Labs)
  // port; anything the operator edits wins and is kept as a patch.
  type FormValues = {
    port: string
    baud_rate: string
    data_bits: string
    parity: string
    stop_bits: string
    flow_control: string
  }
  const [patch, setPatch] = useState<Partial<FormValues>>({})
  const form: FormValues = {
    port: status?.port ?? ports.data?.suggested_port ?? '',
    baud_rate: status?.baud_rate ? String(status.baud_rate) : '115200',
    data_bits: '8',
    parity: 'N',
    stop_bits: '1',
    flow_control: 'none',
    ...patch,
  }
  const setForm = (updater: (current: FormValues) => FormValues) =>
    setPatch(updater(form))

  const portList = ports.data?.ports ?? []
  // Hover on the closed trigger must still reveal the full device name.
  const selectedPortDescription = portList.find(
    (p) => p.device === form.port
  )?.description

  return (
    <PageShell
      title='系统设置'
      subtitle='Console settings'
      toolbar={
        <Button
          size='sm'
          variant='outline'
          onClick={() => ports.refetch()}
          disabled={ports.isFetching}
        >
          <RefreshCw /> 重新枚举端口
        </Button>
      }
    >
      <div className='grid max-w-4xl gap-3'>
        <Panel eyebrow='采集链路' title='串口参数'>
          {/* One row on wide screens, two on medium, stacked on narrow. Every
              track is minmax(0,…) so a long port name shrinks instead of
              pushing over its neighbour. */}
          <div className='grid gap-4 min-[420px]:grid-cols-[minmax(0,1fr)_minmax(0,1fr)] sm:grid-cols-[minmax(0,2fr)_minmax(0,1fr)] xl:grid-cols-[minmax(260px,2fr)_minmax(150px,1fr)_auto_minmax(110px,auto)]'>
            <Field label='串口' hint='优先自动识别 CP210x / Silicon Labs'>
              <Select
                value={form.port}
                onValueChange={(v) => setForm((f) => ({ ...f, port: v }))}
              >
                <SelectTrigger
                  className='w-full min-w-0 [&>[data-slot=select-value]]:block [&>[data-slot=select-value]]:min-w-0 [&>[data-slot=select-value]]:overflow-hidden [&>[data-slot=select-value]]:text-ellipsis [&>[data-slot=select-value]]:whitespace-nowrap'
                  title={selectedPortDescription ?? undefined}
                >
                  <SelectValue placeholder='未检测到串口' />
                </SelectTrigger>
                <SelectContent>
                  {portList.length === 0 ? (
                    <div className='px-2 py-3 text-[12px] text-muted-foreground'>
                      当前系统无可用串口
                    </div>
                  ) : null}
                  {portList.map((p) => (
                    <SelectItem
                      key={p.device}
                      value={p.device}
                      title={`${p.device} ${p.description ?? ''}`.trim()}
                    >
                      <span className='readout me-2 shrink-0'>{p.device}</span>
                      {/* full text, never sliced: the dropdown grows to fit it,
                          only the closed trigger clips it with an ellipsis */}
                      <span className='text-muted-foreground'>
                        {p.suggested ? '· 推荐 ' : ''}
                        {p.description ?? ''}
                      </span>
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </Field>

            <Field label='波特率'>
              <Select
                value={form.baud_rate}
                onValueChange={(v) => setForm((f) => ({ ...f, baud_rate: v }))}
              >
                <SelectTrigger className='w-full'>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {BAUD_RATES.map((b) => (
                    <SelectItem key={b} value={b}>
                      {b}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </Field>

            <Field label='数据位 / 校验 / 停止位'>
              <div className='flex min-w-0 flex-wrap items-center gap-2'>
                <Input
                  className='readout w-16 text-center'
                  value={form.data_bits}
                  onChange={(e) =>
                    setForm((f) => ({ ...f, data_bits: e.target.value }))
                  }
                />
                <Select
                  value={form.parity}
                  onValueChange={(v) => setForm((f) => ({ ...f, parity: v }))}
                >
                  <SelectTrigger className='w-28'>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {PARITIES.map((p) => (
                      <SelectItem key={p.value} value={p.value}>
                        {p.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <Input
                  className='readout w-16 text-center'
                  value={form.stop_bits}
                  onChange={(e) =>
                    setForm((f) => ({ ...f, stop_bits: e.target.value }))
                  }
                />
              </div>
            </Field>

            <Field label='流控'>
              <Select
                value={form.flow_control}
                onValueChange={(v) => setForm((f) => ({ ...f, flow_control: v }))}
              >
                <SelectTrigger className='w-full'>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {FLOW.map((f) => (
                    <SelectItem key={f.value} value={f.value}>
                      {f.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </Field>

            <div className='col-span-full flex flex-wrap items-end justify-end gap-2'>
              <Button
                variant='outline'
                disabled={pending !== null || !form.port}
                onClick={() => {
                  void disconnect()
                  toast.success('已请求断开链路')
                }}
              >
                <Unplug /> 断开
              </Button>
              <Button
                disabled={pending !== null}
                onClick={async () => {
                  const res = await connect({
                    port: form.port,
                    baud_rate: Number(form.baud_rate),
                    data_bits: Number(form.data_bits),
                    parity: form.parity,
                    stop_bits: Number(form.stop_bits),
                    flow_control: form.flow_control,
                  })
                  if (USE_MOCK) {
                    toast.info('演示模式：未调用后端，参数仅作展示')
                    return
                  }
                  if (res?.ok) toast.success(`已连接 ${res.port}`)
                  else toast.error(res?.message ?? '连接失败')
                }}
              >
                <Cable /> 建立链路
              </Button>
            </div>
          </div>

          <Separator className='my-4' />
          <div className='grid gap-2 text-[11.5px] text-muted-foreground'>
            <div className='flex flex-wrap items-center gap-x-5 gap-y-1.5'>
              <span className='inline-flex items-center gap-2'>
                <span
                  className={cn(
                    'size-1.5 rounded-full',
                    toneDot[serialStateTone[status?.state ?? 'disconnected']]
                  )}
                  aria-hidden='true'
                />
                <span className='text-foreground'>
                  {serialStateLabel[status?.state ?? 'disconnected']}
                </span>
              </span>
              {state === 'receiving' ? (
                <span>
                  已接收{' '}
                  <span className='readout text-foreground'>
                    {status?.records_in_batch ?? 0}
                  </span>{' '}
                  条
                </span>
              ) : null}
              {state === 'connected_waiting' && lastBatch ? (
                <span>
                  本批接收完成 · 共{' '}
                  <span className='readout text-foreground'>
                    {lastBatch.record_count}
                  </span>{' '}
                  条 · 等待下一次导出
                </span>
              ) : null}
              {state === 'connected_waiting' && !lastBatch ? (
                <span>在 DHJ-9 上点击「导出记录」开始接收</span>
              ) : null}
            </div>
            <div className='flex flex-wrap items-center gap-x-5 gap-y-1'>
              <span>
                已收行：<span className='readout'>{formatInt(status?.rx_line_count)}</span>
              </span>
              <span>
                解析失败：
                <span className='readout'>{formatInt(status?.parse_error_count)}</span>
              </span>
              <span>不依赖 SSCOM，pyserial 直读 Windows 串口。</span>
            </div>
            {error ? (
              <p className='text-[11.5px] text-signal-alarm'>{error}</p>
            ) : null}
          </div>
        </Panel>

        <Panel
          eyebrow='数据契约'
          title='字段映射（只读）'
          actions={
            <span className='readout-id'>backend/config/parser.yaml</span>
          }
        >
          <ParserFieldTable />
        </Panel>

        <Panel eyebrow='界面' title='显示与外观'>
          <div className='grid gap-4 sm:grid-cols-3'>
            <Field label='主题' hint='中控界面默认深色优先'>
              <Select value={theme} onValueChange={(v) => setTheme(v as typeof theme)}>
                <SelectTrigger className='w-full'>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value='dark'>深色</SelectItem>
                  <SelectItem value='light'>浅色</SelectItem>
                  <SelectItem value='system'>跟随系统</SelectItem>
                </SelectContent>
              </Select>
            </Field>
            <Field label='字体'>
              <Select value={font} onValueChange={(v) => setFont(v as typeof font)}>
                <SelectTrigger className='w-full'>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {fonts.map((f) => (
                    <SelectItem key={f} value={f}>
                      {f}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </Field>
            <Field label='侧边栏'>
              <Select
                value={variant}
                onValueChange={(v) => setVariant(v as typeof variant)}
              >
                <SelectTrigger className='w-full'>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value='inset'>内嵌</SelectItem>
                  <SelectItem value='sidebar'>贴边</SelectItem>
                  <SelectItem value='floating'>浮动</SelectItem>
                </SelectContent>
              </Select>
            </Field>
          </div>
        </Panel>
      </div>
    </PageShell>
  )
}

function ParserFieldTable() {
  const { data, isLoading } = useParserFields()

  if (isLoading) return <Skeleton className='h-40 w-full' />

  return (
    <div className='grid gap-2.5'>
      <Table>
        <TableHeader className='bg-muted/40'>
          <TableRow>
            {['序号', '字段名', '类型', '单位', '含义', '备注'].map((h) => (
              <TableHead key={h}>{h}</TableHead>
            ))}
          </TableRow>
        </TableHeader>
        <TableBody>
          {(data?.fields ?? []).map((f) => (
            <TableRow key={f.index}>
              <TableCell>
                <span className='readout text-[12px]'>{f.index}</span>
              </TableCell>
              <TableCell>
                <span className='readout text-[12px]'>{f.name}</span>
              </TableCell>
              <TableCell>
                <span className='text-[12px] text-muted-foreground'>
                  {f.type}
                </span>
              </TableCell>
              <TableCell>
                <span className='text-[12px] text-muted-foreground'>
                  {f.unit ?? '—'}
                </span>
              </TableCell>
              <TableCell>
                {f.confirmed ? (
                  <span className='inline-flex items-center gap-1 text-[11.5px] text-signal-nominal'>
                    <CircleCheck className='size-3.5' /> 已确认
                  </span>
                ) : (
                  <span className='text-[11.5px] text-muted-foreground'>暂定</span>
                )}
              </TableCell>
              <TableCell>
                <span className='text-[11.5px] text-muted-foreground'>
                  {f.note ?? ''}
                </span>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      <p className='text-[11px] leading-relaxed text-muted-foreground'>
        分隔符 <code className='readout'>,</code> · 每行{' '}
        <code className='readout'>{data?.expected_field_count ?? 12}</code> 列 ·
        批次结束标记 <code className='readout'>{data?.end_of_batch_token ?? 'OVER'}</code>
        。字段含义确认后只需改 <code className='readout'>parser.yaml</code>，
        前端标签与图表绑定会随之更新，无需改代码。
      </p>
    </div>
  )
}
