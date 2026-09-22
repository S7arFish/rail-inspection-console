import { type SVGProps } from 'react'
import { cn } from '@/lib/utils'

/** Two rails in perspective, read as a section of track. */
export function Logo({ className, ...props }: SVGProps<SVGSVGElement>) {
  return (
    <svg
      viewBox='0 0 24 24'
      xmlns='http://www.w3.org/2000/svg'
      height='24'
      width='24'
      fill='none'
      stroke='currentColor'
      strokeWidth='1.7'
      strokeLinecap='round'
      strokeLinejoin='round'
      className={cn('size-6', className)}
      aria-hidden='true'
      {...props}
    >
      <path d='M6.2 21 9.4 3' />
      <path d='M17.8 21 14.6 3' />
      <path d='M7 16.5h10' />
      <path d='M8 11.5h8' />
      <path d='M9 6.5h6' />
    </svg>
  )
}
