import axios from 'axios'
import type {
  ConnectRequest,
  ConnectResponse,
  HealthResponse,
  ParserFieldsResponse,
  PortsResponse,
  SerialStatus,
  SessionDetailResponse,
  SessionListResponse,
} from '@/types/domain'

export const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL ?? '/api',
  timeout: 8000,
})

export const serialApi = {
  ports: () => api.get<PortsResponse>('/serial/ports').then((r) => r.data),
  connect: (body: ConnectRequest = {}) =>
    api.post<ConnectResponse>('/serial/connect', body).then((r) => r.data),
  disconnect: (reason?: string) =>
    api
      .post<Omit<ConnectResponse, 'session_id' | 'port' | 'baud_rate'>>(
        '/serial/disconnect',
        { reason }
      )
      .then((r) => r.data),
  status: () => api.get<SerialStatus>('/serial/status').then((r) => r.data),
}

export const sessionsApi = {
  list: (limit = 50, offset = 0) =>
    api
      .get<SessionListResponse>('/sessions', { params: { limit, offset } })
      .then((r) => r.data),
  detail: (id: string) =>
    api.get<SessionDetailResponse>(`/sessions/${id}`).then((r) => r.data),
}

export const parserApi = {
  fields: () =>
    api.get<ParserFieldsResponse>('/parser/fields').then((r) => r.data),
}

export const healthApi = {
  get: () => api.get<HealthResponse>('/health').then((r) => r.data),
}

/** `/ws/live` resolved against the page origin so the Vite proxy handles it. */
export function liveSocketUrl() {
  const configured = import.meta.env.VITE_WS_URL
  if (configured) return configured
  const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
  return `${proto}://${window.location.host}/ws/live`
}
