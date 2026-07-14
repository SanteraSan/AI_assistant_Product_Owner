// Same-origin with Vite proxy → BFF. Empty string keeps requests on :5173.
export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? ''

/** External Grafana ops UI (admin deep-link). Empty disables the TopBar button. */
export const GRAFANA_URL =
  import.meta.env.VITE_GRAFANA_URL ?? 'http://localhost:3000'
