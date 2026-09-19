// @vitest-environment node
import { afterEach, describe, expect, test, vi } from 'vitest'
import { existsSync, readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import { execFileSync } from 'node:child_process'
import { join } from 'node:path'
import { createServer } from 'vite'
import createConfig from '../vite.config.mjs'

const require = createRequire(import.meta.url)
const express = require('express')
const servers = []
const viteServers = []
afterEach(async () => {
  vi.unstubAllEnvs()
  await Promise.all(viteServers.splice(0).map(server => server.close()))
  await Promise.all(servers.splice(0).map(server => new Promise(resolve => server.close(resolve))))
})
async function middlewareServer (config, preview = false) {
  const app = express()
  const plugin = config.plugins.find(item => item.name === 'oj-runtime')
  plugin[preview ? 'configurePreviewServer' : 'configureServer']({ middlewares: app })
  app.use((req, res) => res.json({ path: req.url }))
  const server = app.listen(0, '127.0.0.1')
  servers.push(server)
  await new Promise((resolve, reject) => { server.once('listening', resolve); server.once('error', reject) })
  return `http://127.0.0.1:${server.address().port}`
}

describe('deployment and mock build contracts', () => {
  test('all production modes ignore mock environment flags', () => {
    for (const key of ['MOCK', 'MOCK_PREVIEW', 'AI_FEATURES_MOCK', 'LEARNING_PATH_MOCK']) vi.stubEnv(key, '1')
    for (const mode of ['production', 'mock', 'development']) {
      const config = createConfig({ command: 'build', mode })
      expect(config.define['process.env.AI_FEATURES_MOCK']).toBe('false')
      expect(config.define['process.env.LEARNING_PATH_MOCK']).toBe('false')
    }
    expect(createConfig({ command: 'serve', mode: 'development' }).define['process.env.AI_FEATURES_MOCK']).toBe('false')
    expect(createConfig({ command: 'serve', mode: 'mock' }).define['process.env.AI_FEATURES_MOCK']).toBe('true')
  })
  test('real backend proxy preserves TARGET and Referer; mock has no proxy', () => {
    const target = 'http://127.0.0.1:18000'
    vi.stubEnv('TARGET', target)
    const config = createConfig({ command: 'serve', mode: 'development' })
    for (const path of ['/api', '/public']) {
      const proxy = config.server.proxy[path]
      expect(proxy.target).toBe(target)
      expect(proxy.changeOrigin).toBe(true)
      let onRequest
      proxy.configure({ on (event, callback) { expect(event).toBe('proxyReq'); onRequest = callback } })
      const setHeader = vi.fn()
      onRequest({ setHeader })
      expect(setHeader).toHaveBeenCalledWith('Referer', target)
    }
    const mock = createConfig({ command: 'serve', mode: 'mock' })
    expect(mock.server.proxy).toBeUndefined()
    expect(mock.server.host).toBe('127.0.0.1')
  })
  test('two HTML entries retain deployment layout and CDN build base', () => {
    vi.stubEnv('STATIC_CDN_HOST', 'https://cdn.example.test/')
    const config = createConfig({ command: 'build', mode: 'production' })
    expect(config.appType).toBe('mpa')
    expect(config.base).toBe('https://cdn.example.test/')
    expect(config.build.assetsDir).toBe('static')
    expect(config.build.rollupOptions.input.oj).toBe(join(config.root, 'index.html'))
    expect(config.build.rollupOptions.input.admin).toBe(join(config.root, 'admin/index.html'))
    for (const html of Object.values(config.build.rollupOptions.input)) {
      expect(existsSync(html)).toBe(true)
      expect(readFileSync(html, 'utf8')).toContain('type="module"')
    }
    expect(createConfig({ command: 'serve', mode: 'development' }).base).toBe('/')
  })
  test('mock serves fixtures before HTML fallback, and keeps OJ/admin deep links distinct', async () => {
    const base = await middlewareServer(createConfig({ command: 'serve', mode: 'mock' }))
    for (const [path, expected] of [['/user-home?tab=learning-feedback', '/index.html'], ['/contest/1/problem/1002/', '/index.html'], ['/admin', '/admin/index.html'], ['/admin/problem/edit/1', '/admin/index.html']]) {
      const response = await fetch(base + path, { headers: { Accept: 'text/html' } })
      expect((await response.json()).path).toBe(expected)
    }
    const profile = await fetch(base + '/api/profile', { headers: { Accept: 'text/html' } })
    expect((await profile.json()).data.user.username).toBe('mock_student')
    expect((await fetch(base + '/public/unknown')).status).toBe(404)
    const asset = await fetch(base + '/static/css/loader.css')
    expect(asset.status).toBe(200)
    expect(asset.headers.get('content-type')).toContain('text/css')
    const unknown = await fetch(base + '/api/not-a-real-endpoint')
    expect((await unknown.json()).error).toBe('mock_error')
  })
  test('real Vite Connect server supports Express responses and both HTML deep links', async () => {
    const config = createConfig({ command: 'serve', mode: 'mock' })
    const server = await createServer({
      ...config,
      configFile: false,
      cacheDir: config.root + '/node_modules/.vite-contract-tests',
      mode: 'mock',
      server: { ...config.server, port: 0, strictPort: false },
      optimizeDeps: { noDiscovery: true, include: [] }
    })
    viteServers.push(server)
    await server.listen()
    const base = `http://127.0.0.1:${server.httpServer.address().port}`
    const profile = await fetch(base + '/api/profile')
    expect(profile.status).toBe(200)
    expect(profile.headers.get('content-type')).toContain('application/json')
    expect((await profile.json()).data.user.username).toBe('mock_student')
    const forbidden = await fetch(base + '/api/admin/problem')
    expect(forbidden.status).toBe(403)
    expect((await forbidden.json()).error).toBe('permission_denied')
    for (const [path, entry] of [['/user-home?tab=learning-feedback', '/src/pages/oj/index.js'], ['/admin/problem/edit/1', '/src/pages/admin/index.js']]) {
      const response = await fetch(base + path, { headers: { Accept: 'text/html' } })
      expect(response.status).toBe(200)
      expect(await response.text()).toContain(entry)
    }
    const apiSource = await fetch(base + '/src/pages/oj/views/user/learningFeedbackApi.js')
    expect(apiSource.status).toBe(200)
    expect(await apiSource.text()).toContain('mock_feedback')
  }, 20000)
  test('real Vite proxy forwards backend paths, session cookie and TARGET Referer', async () => {
    const backend = express()
    backend.use((req, res) => res.json({ path: req.url, referer: req.headers.referer, cookie: req.headers.cookie }))
    const upstream = backend.listen(0, '127.0.0.1')
    servers.push(upstream)
    await new Promise((resolve, reject) => { upstream.once('listening', resolve); upstream.once('error', reject) })
    const target = `http://127.0.0.1:${upstream.address().port}`
    vi.stubEnv('TARGET', target)
    const config = createConfig({ command: 'serve', mode: 'development' })
    const server = await createServer({ ...config, configFile: false, cacheDir: config.root + '/node_modules/.vite-contract-tests', mode: 'development', server: { ...config.server, port: 0, strictPort: false }, optimizeDeps: { noDiscovery: true, include: [] } })
    viteServers.push(server)
    await server.listen()
    for (const path of ['/api/probe?fixture=1', '/public/mock-file.txt']) {
      const response = await fetch(`http://127.0.0.1:${server.httpServer.address().port}${path}`, { headers: { Cookie: 'sessionid=mock-fixture' } })
      expect(response.status).toBe(200)
      expect(await response.json()).toEqual({ path, referer: target, cookie: 'sessionid=mock-fixture' })
    }
  }, 20000)
  test('dependency tree contains only Vue 3 and no migration compatibility runtime', () => {
    const tree = JSON.parse(execFileSync('npm', ['ls', 'vue', '@vue/compat', 'vue-template-compiler', '--all', '--json'], { cwd: createConfig({ command: 'build', mode: 'production' }).root, encoding: 'utf8' }))
    const versions = []
    function visit (dependencies) {
      for (const [name, node] of Object.entries(dependencies || {})) {
        expect(name).not.toBe('@vue/compat')
        expect(name).not.toBe('vue-template-compiler')
        if (name === 'vue') versions.push(node.version)
        visit(node.dependencies)
      }
    }
    visit(tree.dependencies)
    expect(versions.length).toBeGreaterThan(0)
    expect(versions.every(version => version.startsWith('3.'))).toBe(true)
    expect(new Set(versions).size).toBe(1)
  })
})
