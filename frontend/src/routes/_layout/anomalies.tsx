import { createFileRoute } from '@tanstack/react-router'
import { Anomalies } from '@/features/anomalies'

export const Route = createFileRoute('/_layout/anomalies')({
  component: Anomalies,
})
