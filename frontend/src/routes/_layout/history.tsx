import { createFileRoute } from '@tanstack/react-router'
import { History } from '@/features/history'

export const Route = createFileRoute('/_layout/history')({
  component: History,
})
