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
async function request (path, body, method = body ? 'POST' : 'GET') {
  const response = await fetch(base + path, { method, headers: { 'content-type': 'application/json' }, body: body ? JSON.stringify(body) : undefined })
  return { response, status: response.status, body: await response.json() }
}
const role = value => request('/__mock/session', { role: value })

describe('development-only site fixtures', () => {
  test('defaults to student; login and role switching maintain identity', async () => {
    expect((await request('/profile')).body.data.user.username).toBe('mock_student')
    expect((await request('/submission?id=mock-001')).body.data.create_time).toBe('2026-09-19T06:00:00Z')
    expect((await request('/learning-feedback')).body.data.range.end).toBe('2026-09-19T06:00:00.000Z')
    await request('/login', { username: 'mock_admin', password: 'mock' })
    expect((await request('/profile')).body.data.user.admin_type).toBe('Super Admin')
    await role('other')
    expect((await request('/profile')).body.data.user.id).toBe(3)
    await role('guest')
    expect((await request('/profile')).body.data).toBeNull()
    expect((await request('/__mock/session', { role: 'invalid' })).status).toBe(400)
  })
  test('ACM/OI/private/future contests expose fixed browse and permission cases', async () => {
    expect((await request('/contests')).body.data.total).toBe(4)
    expect((await request('/contest/problem?contest_id=1')).body.data).toHaveLength(3)
    expect((await request('/contest/problem?contest_id=3')).status).toBe(403)
    expect((await request('/contest/password', { contest_id: 3, password: 'wrong' })).body.error).toBe('invalid_password')
    await request('/contest/password', { contest_id: 3, password: 'mock123' })
    expect((await request('/contest/problem?contest_id=3')).status).toBe(200)
    await role('other')
    expect((await request('/contest/problem?contest_id=3')).status).toBe(403)
    expect((await request('/contest/problem?contest_id=4')).status).toBe(403)
    expect((await request('/submission', { problem_id: 1, contest_id: 2, code: 'code' })).status).toBe(403)
    expect((await request('/contest_rank?contest_id=2')).body.data.results[0].total_score).toBe(200)
  })
  test('admin lists, upload and download routes reject student and guest', async () => {
    for (const path of ['/admin/user', '/admin/problem', '/admin/test_case?id=1', '/admin/download_submissions?contest_id=1']) expect((await request(path)).status).toBe(403)
    expect((await request('/admin/test_case', {})).status).toBe(403)
    expect((await request('/admin/upload_image', {})).status).toBe(403)
    await role('guest')
    expect((await request('/admin/user')).status).toBe(401)
    expect((await request('/upload_avatar', {})).status).toBe(401)
  })
  test('admin form mutations are reflected and scoped to this fixture instance', async () => {
    await role('admin')
    expect((await request('/admin/dashboard_info')).body.data.user_count).toBe(3)
    const created = await request('/admin/problem/tags', { name: '测试标签', aliases: [], is_active: true })
    expect(created.body.data.id).toBe(5)
    await request('/admin/problem/tags', { id: 5, name: '改名标签' }, 'PUT')
    expect((await request('/admin/problem/tags?id=5')).body.data.name).toBe('改名标签')
    await request('/admin/problem/tags?id=5', undefined, 'DELETE')
    expect((await request('/admin/problem/tags')).body.data).toHaveLength(4)
    const upload = await request('/admin/test_case', {})
    expect(upload.body.data.info[0].input_name).toBe('1.in')
    const response = await fetch(base + '/admin/test_case?id=1')
    expect(response.headers.get('content-disposition')).toContain('attachment; filename=')
    expect(await response.text()).toContain('Mock fixture')
  })
  test('public data download respects per-problem visibility', async () => {
    const publicCase = await fetch(base + '/dl_test_case?problem_id=1')
    expect(publicCase.status).toBe(200)
    expect(publicCase.headers.get('content-disposition')).toContain('attachment')
    expect((await request('/dl_test_case?problem_id=2')).status).toBe(403)
    expect((await request('/contest_rank?contest_id=1&download_csv=1')).status).toBe(403)
  })
  test('contest announcements retain the array contract while global announcements remain paginated', async () => {
    expect(Array.isArray((await request('/contest/announcement?contest_id=1')).body.data)).toBe(true)
    await role('admin')
    const contest = (await request('/admin/contest/announcement?contest_id=1')).body.data
    const global = (await request('/admin/announcement?offset=0&limit=10')).body.data
    expect(Array.isArray(contest)).toBe(true)
    expect(contest[0].title).toBe('Mock 实验说明')
    expect(global.total).toBe(1)
    expect(Array.isArray(global.results)).toBe(true)
    const helper = (await request('/admin/contest/acm_helper?contest_id=1')).body.data
    expect(Array.isArray(helper)).toBe(true)
    expect(helper[0].ac_info.is_first_ac).toBe(true)
    expect((await request('/admin/import_problem', {})).body.data.import_count).toBe(1)
  })
  test('public compiler help and password-form captcha return display-safe fixtures', async () => {
    await role('guest')
    const languages = (await request('/languages')).body.data.languages
    expect(languages).toHaveLength(2)
    for (const language of languages) expect(language.config.compile.compile_command).toContain('Mock only')
    const captcha = (await request('/captcha')).body.data
    expect(captcha.startsWith('data:image/svg+xml;base64,')).toBe(true)
    expect(Buffer.from(captcha.split(',')[1], 'base64').toString()).toContain('MOCK')
    await role('student')
    const qr = (await request('/two_factor_auth')).body.data
    expect(qr.startsWith('data:image/svg+xml;base64,')).toBe(true)
  })
})
