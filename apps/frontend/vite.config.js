import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { pyodideRuntimePlugin } from './scripts/vite-plugin-pyodide-runtime.mjs'
import { duckdbRuntimePlugin } from './scripts/vite-plugin-duckdb-runtime.mjs'
import { runtimeAssetsPlugin } from './scripts/vite-plugin-runtime-assets.mjs'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss(), pyodideRuntimePlugin(), duckdbRuntimePlugin(), runtimeAssetsPlugin()],
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.js'],
  },
})