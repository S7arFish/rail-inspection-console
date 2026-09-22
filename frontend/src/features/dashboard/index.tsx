import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { PageShell } from '@/components/layout/page-shell'
import { useLiveFeedContext } from '@/context/live-feed-provider'
import { fetchMeasurements, fetchTrackPoints } from '@/lib/data-source'
import { LinkBanner } from './components/link-banner'
import { MetricGrid } from './components/metric-grid'
import { TrackStrip } from './components/track-strip'
import { TrendChart } from './components/trend-chart'
import { ReviewList } from './components/review-list'
import { RawTap } from './components/raw-tap'

export function Dashboard() {
  const { samples, latest, status } = useLiveFeedContext()
  const [selectedPoint, setSelectedPoint] = useState<number | null>(null)

  // History seeds the chart so a fresh page is not an empty plot while the
  // live window fills up; new rows arrive over the same feed the tiles use.
  // `batch_count` is in the key so a finished export re-reads its own session.
  const history = useQuery({
    queryKey: [
      'measurements',
      'recent',
      status?.session_id ?? null,
      status?.batch_count ?? 0,
    ],
    queryFn: () => fetchMeasurements(),
  })
  const track = useQuery({
    queryKey: ['track-points'],
    queryFn: fetchTrackPoints,
  })

  const plotted = useMemo(
    () => [...(history.data ?? []), ...samples],
    [history.data, samples]
  )
  const historyLast = history.data?.length
    ? history.data[history.data.length - 1]
    : null
  const previous =
    samples.length > 1 ? samples[samples.length - 2] : historyLast

  return (
    <PageShell
      title='实时监测'
      subtitle='Live monitoring'
      fixed={false}
      toolbar={
        <span className='hidden text-[11px] text-muted-foreground md:inline'>
          {latest ? `末样本 #${latest.id}` : '等待样本'}
        </span>
      }
    >
      <div className='grid gap-3'>
        <LinkBanner />
        <MetricGrid latest={latest} previous={previous} />
        <TrackStrip
          points={track.data ?? []}
          selected={selectedPoint}
          onSelect={(i) => setSelectedPoint((cur) => (cur === i ? null : i))}
        />
        <div className='grid gap-3 xl:grid-cols-3'>
          <div className='xl:col-span-2'>
            <TrendChart samples={plotted} />
          </div>
          <ReviewList />
        </div>
        <RawTap />
      </div>
    </PageShell>
  )
}
