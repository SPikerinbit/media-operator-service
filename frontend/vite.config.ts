import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwind from '@tailwindcss/vite'

const version = readFileSync(resolve(dirname(fileURLToPath(import.meta.url)), '../VERSION'), 'utf8').trim()

export default defineConfig({
  plugins: [react(), tailwind()],
  base: '/static/desktop-ui/',
  define: { __APP_VERSION__: JSON.stringify(version) },
  build: { outDir: '../app/static/desktop-ui', emptyOutDir: true, target: 'chrome110' },
})
