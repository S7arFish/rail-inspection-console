import { createContext, useCallback, useContext, useMemo, useState } from 'react'
import { serialApi } from '@/lib/api-client'
import { USE_MOCK } from '@/lib/data-source'
import { useLiveFeed, type LiveFeed } from '@/hooks/use-live-feed'
import type { ConnectRequest, ConnectResponse } from '@/types/domain'

type LinkAction = 'connect' | 'disconnect' | null

type LiveFeedContext = LiveFeed & {
  /** in-flight link action, so buttons can lock without a second store */
  pending: LinkAction
  error: string | null
  connect: (req?: ConnectRequest) => Promise<ConnectResponse | null>
  disconnect: () => Promise<void>
}

const LiveFeedContextObject = createContext<LiveFeedContext | null>(null)

/**
 * One WebSocket / mock ticker for the whole shell: the sidebar status block and
 * the dashboard both read from here instead of opening their own transport.
 */
export function LiveFeedProvider({ children }: { children: React.ReactNode }) {
  const feed = useLiveFeed()
  const [pending, setPending] = useState<LinkAction>(null)
  const [error, setError] = useState<string | null>(null)

  const connect = useCallback(
    async (req: ConnectRequest = {}) => {
      if (USE_MOCK) return null
      setPending('connect')
      setError(null)
      try {
        const res = await serialApi.connect(req)
        if (!res.ok) setError(res.message)
        return res
      } catch (e) {
        setError(e instanceof Error ? e.message : '建立链路失败')
        return null
      } finally {
        setPending(null)
        void feed.refetchStatus()
      }
    },
    [feed]
  )

  const disconnect = useCallback(async () => {
    if (USE_MOCK) return
    setPending('disconnect')
    setError(null)
    try {
      await serialApi.disconnect()
    } catch (e) {
      setError(e instanceof Error ? e.message : '断开链路失败')
    } finally {
      setPending(null)
      void feed.refetchStatus()
    }
  }, [feed])

  const value = useMemo(
    () => ({ ...feed, pending, error, connect, disconnect }),
    [feed, pending, error, connect, disconnect]
  )

  return (
    <LiveFeedContextObject value={value}>{children}</LiveFeedContextObject>
  )
}

// eslint-disable-next-line react-refresh/only-export-components
export function useLiveFeedContext() {
  const ctx = useContext(LiveFeedContextObject)
  if (!ctx)
    throw new Error('useLiveFeedContext must be used within LiveFeedProvider')
  return ctx
}
