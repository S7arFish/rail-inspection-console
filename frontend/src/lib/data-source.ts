import { parserApi, serialApi, sessionsApi } from './api-client'
import {
  mockMeasurements,
  mockParserFields,
  mockPorts,
  mockReviewItems,
  mockSessions,
  mockStatus,
  mockTrackPoints,
} from '@/mock/fixtures'
import type {
  ParserFieldsResponse,
  SerialStatus,
  SessionListResponse,
} from '@/types/domain'
import type { ReviewItem, TrackPoint } from '@/types/console'

/** Flip to `false` (or set VITE_USE_MOCK=false) to talk to FastAPI. */
export const USE_MOCK = (import.meta.env.VITE_USE_MOCK ?? 'true') !== 'false'

export async function fetchParserFields(): Promise<ParserFieldsResponse> {
  if (USE_MOCK) return mockParserFields
  return parserApi.fields()
}

export async function fetchSerialStatus(): Promise<SerialStatus> {
  if (USE_MOCK) return mockStatus
  return serialApi.status()
}

/** Which port the car's sensor unit is on is always a hardware question. */
export async function fetchPorts() {
  if (USE_MOCK) return mockPorts
  return serialApi.ports()
}

export async function fetchSessions(
  limit = 50,
  offset = 0
): Promise<SessionListResponse> {
  if (USE_MOCK) {
    const items = mockSessions()
    return { items: items.slice(offset, offset + limit), total: items.length }
  }
  return sessionsApi.list(limit, offset)
}

/**
 * Samples for the panel that wants "the current stretch".
 *
 * A DHJ-9 batch is one session, and between exports there is no open session —
 * so fall back to the most recent one instead of showing an empty dashboard.
 */
export async function fetchMeasurements(sessionId?: string) {
  if (USE_MOCK) return mockMeasurements()
  let id = sessionId
  if (!id) id = (await serialApi.status()).session_id ?? undefined
  if (!id) id = (await sessionsApi.list(1, 0)).items[0]?.id
  if (!id) return []
  const detail = await sessionsApi.detail(id)
  return detail.samples
}

export async function fetchReviewItems(): Promise<ReviewItem[]> {
  if (USE_MOCK) return mockReviewItems(mockMeasurements())
  // No anomaly endpoint is defined yet; see README "下一步".
  return []
}

export async function fetchTrackPoints(): Promise<TrackPoint[]> {
  if (USE_MOCK) return mockTrackPoints(mockMeasurements())
  return []
}
