import path from 'node:path'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    port: 5173,
    // Simulator tick writes JSON under backend/ — ignore so Vite doesn't full-reload the UI every second
    watch: {
      ignored: ["**/backend/**", "**/simulator/**", "**/*.jsonl"],
    },
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
      },
    },
  },
  // maplibre-gl ships its own web worker bundle; letting Vite's dep optimizer
  // pre-bundle it produces a broken reference to that worker file (seen as
  // "file does not exist ... maplibre-gl-worker.mjs" in the dev server log).
  optimizeDeps: {
    exclude: ['maplibre-gl'],
  },
})
