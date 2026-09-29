import { createRequire } from 'node:module'
import { afterEach, beforeEach, describe, expect, test } from 'vitest'

const require = createRequire(import.meta.url)
const express = require('express')
const mockApi = require('../build/mock-api')
let server
let base

beforeEach(async () => {
  const app = express()
  app.use('/api', mockApi())
  server = app.listen(0, '127.0.0.1')
  await new Promise((resolve, reject) => { server.once('listening', resolve); server.once('error', reject) })
  base = `http://127.0.0.1:${server.address().port}/api`
})
afterEach(async () => { if (server && server.listening) await new Promise(resolve => server.close(resolve)) })

async function get (path) {
  const response = await fetch(base + path)
  return { status: response.status, body: await response.json() }
}

describe('public knowledge Mock contract', () => {
  test('list filters and pages the shared seed data', async () => {
    const first = await get('/knowledge-points?page_size=10')
    expect(first.body.data.total).toBe(12)
    expect(first.body.data.items).toHaveLength(10)
    const second = await get('/knowledge-points?page=2&page_size=10')
    expect(second.body.data.items).toHaveLength(2)
    const bfs = await get('/knowledge-points?keyword=%E5%B9%BF%E6%90%9C')
    expect(bfs.body.data.items.map(item => item.code)).toContain('bfs_basic')
    const empty = await get('/knowledge-points?category=mathematics')
    expect(empty.body.data.items).toEqual([])
  })

  test('root graph traverses in both directions, then filters while retaining root', async () => {
    const graph = (await get('/knowledge-graph?root_code=bfs_basic&depth=1')).body.data
    expect(graph.nodes.map(node => node.code)).toEqual(expect.arrayContaining(['bfs_basic', 'queue_basic', 'grid_bfs', 'bfs_shortest_path', 'adjacency_representation']))
    expect(graph.edges.find(edge => edge.from === 'queue_basic').relation_type).toBe('recommended')
    const filtered = (await get('/knowledge-graph?root_code=bfs_basic&depth=1&category=data_structure')).body.data
    expect(filtered.nodes.map(node => node.code)).toEqual(['bfs_basic', 'queue_basic'])
    expect(filtered.edges).toHaveLength(1)
    const detail = (await get('/knowledge-points/bfs_basic')).body.data
    expect(detail.related_problems).toEqual([{ display_id: '1002', title: '迷宫最短路（BFS）' }])
  })

  test('requires a session and returns knowledge-specific errors', async () => {
    await fetch(base + '/__mock/session', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ role: 'guest' }) })
    for (const path of ['/knowledge-points', '/knowledge-points/bfs_basic', '/knowledge-graph']) {
      const response = await get(path)
      expect(response.status).toBe(401)
      expect(response.body.error).toBe('KNOWLEDGE_AUTH_REQUIRED')
      expect(response.body.request_id).toMatch(/^mock-knowledge-/)
    }
  })
})
