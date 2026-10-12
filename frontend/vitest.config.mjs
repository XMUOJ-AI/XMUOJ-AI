import { defineConfig } from 'vitest/config'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath } from 'node:url'

const at = path => fileURLToPath(new URL(path, import.meta.url))
export default defineConfig({
  plugins: [vue()],
  resolve: { alias: { '@': at('./src'), '@oj': at('./src/pages/oj'), '@admin': at('./src/pages/admin'), '~': at('./src/components') }, extensions: ['.js', '.mjs', '.vue', '.json'] },
  define: { 'process.env.VERSION': '"test"', 'process.env.LEARNING_PATH_MOCK': 'globalThis.__LEARNING_PATH_MOCK__', 'process.env.AI_FEATURES_MOCK': 'globalThis.__AI_FEATURES_MOCK__', 'process.env.USE_SENTRY': '"0"' },
  test: { environment: 'jsdom', globals: true, include: ['tests/**/*.test.js'], restoreMocks: true, setupFiles: ['./tests/setup.js'] }
})
