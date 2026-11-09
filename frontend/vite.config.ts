import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwind from '@tailwindcss/vite'

export default defineConfig({
  plugins: [react(), tailwind()],
  base: '/static/desktop-ui/',
  build: { outDir: '../app/static/desktop-ui', emptyOutDir: true, target: 'chrome110' },
})
