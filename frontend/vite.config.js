import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// In development the browser talks to this server only, and /api is forwarded to the backend.
// Same origin means no CORS configuration is needed locally, and it matches how the production
// nginx image works. Set VITE_API_BASE_URL to call a different API origin directly instead.
const apiTarget = process.env.VITE_DEV_API_TARGET || 'http://127.0.0.1:8000'

export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0',
    port: 3000,
    proxy: {
      '/api': { target: apiTarget, changeOrigin: false },
    },
  },
  preview: {
    host: '0.0.0.0',
    port: 3000,
    proxy: {
      '/api': { target: apiTarget, changeOrigin: false },
    },
  },
})
