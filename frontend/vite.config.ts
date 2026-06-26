import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

const backend = process.env.BACKEND_URL || 'http://127.0.0.1:8000'

export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      '/api': backend,
      '/auth': backend,
      '/jobs': backend,
      '/docs': backend,
      '/openapi.json': backend,
    },
  },
  build: {
    outDir: '../static',
    emptyOutDir: true,
  },
})
