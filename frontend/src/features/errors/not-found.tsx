import { Link } from '@tanstack/react-router'
import { Button } from '@/components/ui/button'

export function NotFound() {
  return (
    <div className='flex min-h-svh items-center justify-center p-6'>
      <div className='panel w-full max-w-sm px-5 py-6 text-center'>
        <p className='readout text-[11px] tracking-[0.2em] text-muted-foreground'>
          HTTP 404
        </p>
        <h1 className='mt-2 text-lg font-semibold'>页面不存在</h1>
        <p className='mt-1.5 text-[12.5px] leading-relaxed text-muted-foreground'>
          该地址不在中控平台的导航内。
        </p>
        <Button asChild variant='outline' size='sm' className='mt-4'>
          <Link to='/'>返回实时监测</Link>
        </Button>
      </div>
    </div>
  )
}
