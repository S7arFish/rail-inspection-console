import {
  ChartLine,
  Gauge,
  ScrollText,
  Settings,
  ShieldAlert,
} from 'lucide-react'
import { type SidebarData } from '../types'

export const sidebarData: SidebarData = {
  navGroups: [
    {
      title: '检测',
      items: [
        { title: '实时监测', url: '/', icon: Gauge },
        { title: '异常检测', url: '/anomalies', icon: ShieldAlert },
        { title: '历史任务', url: '/history', icon: ScrollText },
        { title: '数据分析', url: '/analytics', icon: ChartLine },
      ],
    },
    {
      title: '系统',
      items: [{ title: '系统设置', url: '/settings', icon: Settings }],
    },
  ],
}
