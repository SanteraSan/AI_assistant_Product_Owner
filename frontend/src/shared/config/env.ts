// Same-origin with Vite proxy → BFF. Empty string keeps requests on :5173.
export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? ''
