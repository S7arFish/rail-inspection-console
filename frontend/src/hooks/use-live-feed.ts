import { useCallback, useEffect, useRef, useState } from 'react'
import { liveSocketUrl, serialApi } from '@/lib/api-client'
import { mockStatus, createMockSampleStream } from '@/mock/fixtures'
import { USE_MOCK } from '@/lib/data-source'
import type {
  LiveEvent,
  Measurement,
  ParseError,
  SerialStatus,
  SessionComplete,
} from '@/types/domain'

export interface LiveFeed {
  /** latest link/serial status as pushed by the backend */
  status: SerialStatus | null
  /** rolling window, oldest first */
  samples: Measurement[]
  latest: Measurement | null
  /** the batch closed by the most recent `OVER` */
  lastBatch: SessionComplete | null
  recentErrors: ParseError[]
  /** transport state: is the console receiving anything at all */
  streaming: boolean
  /** mock build, so the UI can say so out loud */
  mocked: boolean
  /** pull status over REST; the WS `status` event is the push equivalent */
  refetchStatus: () => Promise<void>
}

const RECONNECT_MS = 2000
const MAX_SAMPLES = 240
const MAX_ERRORS = 20

export function useLiveFeed(intervalMs = 900): LiveFeed {
  const [status, setStatus] = useState<SerialStatus | null>(
    USE_MOCK ? mockStatus : null
  )
  const [samples, setSamples] = useState<Measurement[]>([])
  const [lastBatch, setLastBatch] = useState<SessionComplete | null>(null)
  const [recentErrors, setRecentErrors] = useState<ParseError[]>([])
  const [streaming, setStreaming] = useState(false)
  const socketRef = useRef<WebSocket | null>(null)

  useEffect(() => {
    if (USE_MOCK) return

    let closedByUs = false
    let retryTimer: number | undefined

    const connect = () => {
      const socket = new WebSocket(liveSocketUrl())
      socketRef.current = socket

      socket.onopen = () => setStreaming(true)
      socket.onclose = () => {
        setStreaming(false)
        socketRef.current = null
        if (!closedByUs) retryTimer = window.setTimeout(connect, RECONNECT_MS)
      }
      socket.onerror = () => setStreaming(false)

      socket.onmessage = (event) => {
        let envelope: LiveEvent
        try {
          envelope = JSON.parse(String(event.data)) as LiveEvent
        } catch {
          return
        }

        switch (envelope.type) {
          case 'laser.snapshot':
            setStatus(envelope.payload.status)
            setSamples(envelope.payload.measurements.slice(-MAX_SAMPLES))
            break
          case 'laser.measurement':
            setSamples((prev) =>
              [...prev, envelope.payload].slice(-MAX_SAMPLES)
            )
            break
          case 'session.complete':
            setLastBatch(envelope.payload)
            break
          case 'laser.status':
            setStatus(envelope.payload)
            break
          case 'laser.parse_error':
            setRecentErrors((prev) => [envelope.payload, ...prev].slice(0, MAX_ERRORS))
            break
          case 'pong':
            break
        }
      }
    }

    connect()
    return () => {
      closedByUs = true
      window.clearTimeout(retryTimer)
      socketRef.current?.close()
      socketRef.current = null
    }
  }, [])

  // Mock transport: emit one parsed row per tick, mirroring the live shape.
  useEffect(() => {
    if (!USE_MOCK) return
    const nextSample = createMockSampleStream()
    let seq = 0

    const id = window.setInterval(() => {
      setStreaming(true)
      const next = nextSample()
      seq += 1
      setSamples((prev) => [...prev, next].slice(-MAX_SAMPLES))
      setStatus((prev) =>
        prev
          ? {
              ...prev,
              sample_count: prev.sample_count + 1,
              rx_line_count: prev.rx_line_count + 1,
              last_line_at: next.ts,
            }
          : prev
      )
      if (seq % 11 === 0) {
        setLastBatch({
          session_id: next.session_id,
          batch_seq: Math.floor(seq / 11),
          record_count: 11,
        })
      }
    }, intervalMs)

    return () => {
      window.clearInterval(id)
      setStreaming(false)
    }
  }, [intervalMs])

  const refetchStatus = useCallback(async () => {
    if (USE_MOCK) {
      setStatus(mockStatus)
      return
    }
    try {
      setStatus(await serialApi.status())
    } catch {
      /* the socket's own open/close state already reports the outage */
    }
  }, [])

  return {
    status,
    samples,
    latest: samples.length ? samples[samples.length - 1] : null,
    lastBatch,
    recentErrors,
    streaming,
    mocked: USE_MOCK,
    refetchStatus,
  }
}
