import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The SPA is served by FastAPI under the /app/ prefix in production, so all
// emitted asset URLs must be prefixed accordingly. During `vite dev` we proxy
// API + auth routes to the local FastAPI server on :8000 so the React app can
// talk to the real backend without CORS gymnastics.
export default defineConfig({
  base: '/app/',
  plugins: [react()],
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    sourcemap: false,
  },
  server: {
    port: 5173,
    proxy: {
      '/api': { target: 'http://localhost:8000', changeOrigin: true },
      '/dashboard': { target: 'http://localhost:8000', changeOrigin: true },
      '/oauth': { target: 'http://localhost:8000', changeOrigin: true },
      '/logout': { target: 'http://localhost:8000', changeOrigin: true },
    },
  },
})
