import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath } from 'node:url'
import { resolve, dirname } from 'node:path'
import { cpSync, existsSync } from 'node:fs'
import { execFileSync } from 'node:child_process'
import { createRequire } from 'node:module'
import express from 'express'

const root = dirname(fileURLToPath(import.meta.url))
const require = createRequire(import.meta.url)
const aliases = { '@': resolve(root, 'src'), '@oj': resolve(root, 'src/pages/oj'), '@admin': resolve(root, 'src/pages/admin'), '~': resolve(root, 'src/components') }
function buildVersion () {
  if (process.env.VERSION) return process.env.VERSION
  let revision = 'source'
  try {
    revision = execFileSync('git', ['rev-parse', '--short=5', 'HEAD'], { cwd: root, encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'] }).trim()
  } catch {
    // Exported sources and the standalone frontend image need no Git metadata.
  }
  return `${new Date().toISOString().slice(0, 10).replaceAll('-', '')}-${revision}`
}
const version = buildVersion()

function appMiddleware (mock, preview = false) {
  const router = express()
  router.disable('x-powered-by')
  if (mock) {
    router.use('/api', require('./build/mock-api.js')())
    router.get('/public/website/favicon.ico', (req, res) => res.status(204).end())
    router.use('/public', (req, res) => res.status(404).end())
  }
  if (!preview) router.use('/static', express.static(resolve(root, 'static')))
  router.use((req, res, next) => {
    const pathname = req.url.split('?')[0]
    if (req.method === 'GET' && req.headers.accept?.includes('text/html') && !pathname.startsWith('/api/') && !pathname.startsWith('/public/')) req.url = pathname === '/admin' || pathname.startsWith('/admin/') ? '/admin/index.html' : '/index.html'
    next()
  })
  return router
}

export default defineConfig(({ command, mode }) => {
  const mock = command === 'serve' && mode === 'mock'
  const target = process.env.TARGET || 'http://127.0.0.1:8000'
  const proxy = Object.fromEntries(['/api', '/public'].map(path => [path, {
    target, changeOrigin: true,
    configure (proxy) { proxy.on('proxyReq', request => request.setHeader('Referer', target)) }
  }]))
  return {
    root,
    appType: 'mpa',
    base: command === 'build' && process.env.STATIC_CDN_HOST ? process.env.STATIC_CDN_HOST.replace(/\/$/, '') + '/' : '/',
    publicDir: false,
    plugins: [vue({ template: { compilerOptions: { whitespace: 'preserve' } } }), {
      name: 'oj-runtime',
      configureServer (server) {
        server.middlewares.use(appMiddleware(mock))
      },
      configurePreviewServer (server) {
        server.middlewares.use(appMiddleware(process.env.MOCK_PREVIEW === '1', true))
      },
      closeBundle () {
        if (command === 'build' && existsSync(resolve(root, 'static'))) cpSync(resolve(root, 'static'), resolve(root, 'dist/static'), { recursive: true, filter: file => !/vendor\.dll\./.test(file) })
      }
    }],
    resolve: {
      // Moment's locale files import its CommonJS entry; use that same instance.
      alias: [{ find: /^moment$/, replacement: resolve(root, 'node_modules/moment/moment.js') }, ...Object.entries(aliases).map(([find, replacement]) => ({ find, replacement }))],
      extensions: ['.mjs', '.js', '.ts', '.jsx', '.tsx', '.json', '.vue'],
      dedupe: ['vue', 'jquery', 'tar-simditor']
    },
    define: {
      'process.env.VERSION': JSON.stringify(version),
      'process.env.USE_SENTRY': JSON.stringify(process.env.USE_SENTRY === '1' && !mock ? '1' : '0'),
      'process.env.LEARNING_PATH_MOCK': JSON.stringify(mock),
      'process.env.AI_FEATURES_MOCK': JSON.stringify(mock)
    },
    css: { preprocessorOptions: { less: { javascriptEnabled: true, math: 'always' } } },
    server: { host: '127.0.0.1', port: Number(process.env.PORT) || 8080, strictPort: true, proxy: mock ? undefined : proxy },
    preview: { host: '127.0.0.1', port: Number(process.env.PORT) || 4173, strictPort: true, proxy: process.env.MOCK_PREVIEW === '1' ? undefined : proxy },
    build: {
      target: ['chrome111', 'edge111', 'firefox114', 'safari16.4'],
      assetsDir: 'static', sourcemap: process.env.USE_SENTRY === '1',
      rollupOptions: { input: { oj: resolve(root, 'index.html'), admin: resolve(root, 'admin/index.html') } }
    }
  }
})
