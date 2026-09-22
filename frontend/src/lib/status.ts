import type { SerialState } from '@/types/domain'

/** The console's whole colour vocabulary. Chromatic = meaning, never décor. */
export type Tone = 'nominal' | 'caution' | 'alarm' | 'unknown' | 'idle'

export const serialStateLabel: Record<SerialState, string> = {
  disconnected: '未连接',
  connecting: '连接中',
  connected_waiting: '等待仪器导出',
  receiving: '正在接收',
  batch_complete: '本批接收完成',
  error: '链路故障',
  reconnecting: '重连中',
}

export const serialStateTone: Record<SerialState, Tone> = {
  disconnected: 'idle',
  connecting: 'caution',
  connected_waiting: 'nominal',
  receiving: 'caution',
  batch_complete: 'nominal',
  error: 'alarm',
  reconnecting: 'caution',
}

/** The port is open in these states — the DHJ-9 exports only on demand. */
export const LINK_UP_STATES: readonly SerialState[] = [
  'connected_waiting',
  'receiving',
  'batch_complete',
]

export const toneLabel: Record<Tone, string> = {
  nominal: '正常',
  caution: '注意',
  alarm: '报警',
  unknown: '未判定',
  idle: '空闲',
}

/** Full literal class names so the Tailwind scanner keeps them. */
export const toneText: Record<Tone, string> = {
  nominal: 'text-signal-nominal',
  caution: 'text-signal-caution',
  alarm: 'text-signal-alarm',
  unknown: 'text-muted-foreground',
  idle: 'text-muted-foreground',
}

export const toneDot: Record<Tone, string> = {
  nominal: 'bg-signal-nominal',
  caution: 'bg-signal-caution',
  alarm: 'bg-signal-alarm',
  unknown: 'bg-signal-idle',
  idle: 'bg-signal-idle',
}

export const toneBadge: Record<Tone, string> = {
  nominal: 'border-signal-nominal/40 text-signal-nominal',
  caution: 'border-signal-caution/40 text-signal-caution',
  alarm: 'border-signal-alarm/45 text-signal-alarm',
  unknown: 'border-border text-muted-foreground',
  idle: 'border-border text-muted-foreground',
}
