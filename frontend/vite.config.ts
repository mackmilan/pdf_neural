import { fileURLToPath } from 'node:url'
import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'

const projectRoot = fileURLToPath(new URL('..', import.meta.url))

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, projectRoot, '')
  const backend = process.env.BACKEND_URL || env.BACKEND_URL || 'http://127.0.0.1:8000'

  return {
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
  }
})
