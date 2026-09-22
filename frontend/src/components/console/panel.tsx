import { cn } from '@/lib/utils'

type PanelProps = {
  title?: React.ReactNode
  eyebrow?: React.ReactNode
  actions?: React.ReactNode
  bodyClassName?: string
  className?: string
  children: React.ReactNode
}

/** Flat console panel: hairline edge, titled header rule, no shadow. */
export function Panel({
  title,
  eyebrow,
  actions,
  bodyClassName,
  className,
  children,
}: PanelProps) {
  return (
    <section className={cn('panel flex min-w-0 flex-col', className)}>
      {(title || actions) && (
        <header className='flex items-center gap-3 border-b px-3.5 py-2.5'>
          <div className='grid min-w-0 leading-tight'>
            {eyebrow ? (
              <span className='label-micro text-[10px]'>{eyebrow}</span>
            ) : null}
            {title ? (
              <span className='truncate text-[13px] font-medium'>{title}</span>
            ) : null}
          </div>
          {actions ? (
            <div className='ms-auto flex shrink-0 items-center gap-1.5'>
              {actions}
            </div>
          ) : null}
        </header>
      )}
      <div className={cn('min-w-0 flex-1 p-3.5', bodyClassName)}>{children}</div>
    </section>
  )
}
