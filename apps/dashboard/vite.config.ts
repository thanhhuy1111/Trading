import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5174,
    proxy: {
      // apps/api/routers/chat.py mounts at the real prefix /api/v1 -- pass through
      // unchanged. Must be registered before the general '/api' rule below since it's a
      // more specific prefix of it.
      '/api/v1': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
      // Every other router (recommendations, trading, portfolio, ...) is mounted with no
      // prefix of its own, so /api/xxx must have the /api stripped before reaching it.
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
    },
  },
})
