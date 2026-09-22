import { Header } from './header'
import { Main } from './main'
import { Search } from '@/components/search'
import { ThemeSwitch } from '@/components/theme-switch'

type PageShellProps = {
  title: string
  subtitle?: React.ReactNode
  toolbar?: React.ReactNode
  /** dashboards want the full width; document pages want a measure */
  fluid?: boolean
  fixed?: boolean
  className?: string
  children: React.ReactNode
}

export function PageShell({
  title,
  subtitle,
  toolbar,
  fluid = true,
  fixed = false,
  className,
  children,
}: PageShellProps) {
  return (
    <>
      <Header fixed className='border-b'>
        <div className='grid leading-tight'>
          <h1 className='truncate text-[15px] font-semibold'>{title}</h1>
          {subtitle ? (
            <span className='label-micro truncate text-[10px]'>{subtitle}</span>
          ) : null}
        </div>
        <div className='ms-auto flex items-center gap-2'>
          {toolbar}
          <Search placeholder='跳转' className='hidden sm:inline-flex' />
          <ThemeSwitch />
        </div>
      </Header>
      <Main fixed={fixed} fluid={fluid} className={className}>
        {children}
      </Main>
    </>
  )
}
