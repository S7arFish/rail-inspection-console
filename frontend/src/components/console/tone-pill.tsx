import { cn } from '@/lib/utils'
import { toneBadge, toneDot, toneLabel, type Tone } from '@/lib/status'

export function TonePill({
  tone,
  label,
  className,
}: {
  tone: Tone
  label?: string
  className?: string
}) {
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-[11px] leading-none',
        toneBadge[tone],
        className
      )}
    >
      <span className={cn('size-1.5 rounded-full', toneDot[tone])} />
      {label ?? toneLabel[tone]}
    </span>
  )
}
