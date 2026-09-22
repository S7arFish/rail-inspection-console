import { Link } from '@tanstack/react-router'
import { Logo } from '@/assets/logo'
import {
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
} from '@/components/ui/sidebar'

export function AppTitle() {
  return (
    <SidebarMenu>
      <SidebarMenuItem>
        <SidebarMenuButton
          size='lg'
          className='gap-2.5 py-0 hover:bg-transparent active:bg-transparent'
          asChild
        >
          <Link to='/' className='grid flex-1 text-start leading-tight'>
            <span className='flex items-center gap-2.5'>
              <span className='flex size-8 shrink-0 items-center justify-center rounded-md border border-sidebar-border text-sidebar-primary'>
                <Logo className='size-4.5' />
              </span>
              <span className='grid'>
                <span className='truncate text-[13px] font-semibold tracking-wide'>
                  轨道检测车中控
                </span>
                <span className='label-micro truncate text-[10px]'>
                  RIC Console
                </span>
              </span>
            </span>
          </Link>
        </SidebarMenuButton>
      </SidebarMenuItem>
    </SidebarMenu>
  )
}
