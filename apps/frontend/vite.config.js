import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { pyodideRuntimePlugin } from './scripts/vite-plugin-pyodide-runtime.mjs'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss(), pyodideRuntimePlugin()],
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.js'],
  },
})