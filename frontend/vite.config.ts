import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig(({ mode }) => {
  const base = loadEnv(mode, '.', '').VITE_BASE_PATH || '/'
  return {
    base,
    plugins: [react(), {
      name: 'contour-shared-css',
      enforce: 'pre',
      transformIndexHtml(html: string) {
        return base.indexOf('/budget/') === 0 ? html : html.replace('    <link rel="stylesheet" href="/contour.css" />\n', '')
      },
    }],
    server: {
      port: 5173,
      proxy: { '/api': { target: 'http://127.0.0.1:8000', changeOrigin: true } },
    },
  }
})
