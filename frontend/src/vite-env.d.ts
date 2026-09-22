/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** REST base URL. Defaults to `/api`, which the Vite dev server proxies. */
  readonly VITE_API_BASE_URL?: string
  /** Full ws:// URL. Defaults to the page origin + `/ws/live`. */
  readonly VITE_WS_URL?: string
  /** `true` keeps the console on fixtures until the backend is wired up. */
  readonly VITE_USE_MOCK?: string
  /** Where `/api` and `/ws` are proxied in dev. */
  readonly VITE_API_PROXY_TARGET?: string
  readonly VITE_PORT?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
