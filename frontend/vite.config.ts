import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwind from '@tailwindcss/vite'
import { fixturePlugin } from './fixture/plugin.mjs'

const version = readFileSync(resolve(dirname(fileURLToPath(import.meta.url)), '../VERSION'), 'utf8').trim()

export default defineConfig({
  plugins: [react(), tailwind(), ...(process.env.WORKBENCH_FIXTURE === '1' ? [fixturePlugin()] : [])],
  base: '/static/desktop-ui/',
  define: { __APP_VERSION__: JSON.stringify(version) },
  build: {
    outDir: '../app/static/desktop-ui',
    emptyOutDir: true,
    target: 'chrome110',
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (id.includes('node_modules/react') || id.includes('node_modules/react-dom')) return 'vendor-react'
          if (id.includes('node_modules/motion') || id.includes('node_modules/framer-motion')) return 'vendor-motion'
          if (id.includes('node_modules/lucide-react')) return 'vendor-icons'
        },
      },
    },
  },
})
