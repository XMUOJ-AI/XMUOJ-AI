import assert from 'node:assert'
import fs from 'node:fs'
import vm from 'node:vm'
import { createRequire } from 'node:module'
import { nextTick } from 'vue'
import { flushPromises } from '@vue/test-utils'
import { mountLogic, reactiveState } from './componentHarness'
import { beforeEach, test, vi } from 'vitest'
import Component from '../src/pages/oj/views/problem/ProblemGuidance.vue'
import * as data from '../src/pages/oj/views/problem/problemGuidanceData.js'
const require = createRequire(import.meta.url)
const injected = vi.hoisted(() => ({ api: {}, axios: {} }))
vi.mock('../src/pages/oj/views/problem/problemGuidanceApi.js', () => ({ default: new Proxy({}, { get: (_, key) => (...args) => injected.api[key](...args) }) }))
vi.mock('axios', () => ({ default: { create: config => new Proxy(options => injected.axios.create(config)(options), { get: (_, key) => (...args) => injected.axios.create(config)[key](...args) }) } }))
const actualApi = await vi.importActual('../src/pages/oj/views/problem/problemGuidanceApi.js')
beforeEach(() => { globalThis.__AI_FEATURES_MOCK__ = true; globalThis.__LEARNING_PATH_MOCK__ = true })
function load (filename, imports = {}, mock = true) {
  globalThis.__AI_FEATURES_MOCK__ = mock
  vi.stubGlobal('process', { ...process, env: { ...process.env, AI_FEATURES_MOCK: mock } })
  if (imports.axios) injected.axios = imports.axios
  if (imports['./problemGuidanceApi']) injected.api = imports['./problemGuidanceApi']
  if (filename === 'ProblemGuidance.vue') return { default: Component }
  if (filename === 'problemGuidanceData.js') return data

  if (filename === 'problemGuidanceApi.js') return actualApi
  throw new Error('Unexpected test module: ' + filename)
}

const fixture = (problem = '1002', contest = null, user = '1') => ({
  user_id: user,
  context: { problem_id: problem, contest_id: contest },
  session_id: 's-' + problem,
  capabilities: { can_request: true, contest_allowed: false },
  status: 'ready',
  stage: 'understand',
  quota: { limit: 3, remaining: 3 },
  available_at: null,
  server_time: new Date().toISOString(),
  messages: [],
  last_request_id: null
})
const expected = { user_id: '1', problem_id: '1002', contest_id: null }
assert.strictEqual(data.normalizeGuidance(fixture(), expected).allowed, true)
for (const corrupt of [
  p => { p.context.problem_id = '1003' }, p => { p.user_id = '2' }, p => { p.context.contest_id = [] },
  p => { p.messages = {} }, p => { p.messages = [null] }, p => { p.capabilities = null },
  p => { p.quota.remaining = -1 }, p => { p.quota.remaining = 4 }, p => { p.server_time = 'invalid' },
  p => { p.status = 'waiting' }, p => { p.stage = 'answer' }, p => { p.session_id = {} }
]) {
  const raw = fixture(); corrupt(raw)
  assert.throws(() => data.normalizeGuidance(raw, expected), error => error.code === 'invalid_data')
}
assert.throws(() => data.normalizeGuidance(fixture(), { ...expected, session_id: 'other-session' }))
assert.strictEqual(data.normalizeGuidance({ ...fixture(), status: 'future' }, expected).allowed, false)
const contest = fixture('1002', '7')
assert.strictEqual(data.normalizeGuidance(contest, { ...expected, contest_id: '7' }).allowed, false)
contest.capabilities.contest_allowed = true
assert.strictEqual(data.normalizeGuidance(contest, { ...expected, contest_id: '7' }).allowed, true)
function deferred () { const result = {}; result.promise = new Promise((resolve, reject) => { result.resolve = resolve; result.reject = reject }); return result }
async function settle () { await nextTick(); await Promise.resolve(); await Promise.resolve() }
async function componentTests () {
  const requests = []
  const api = {}
  for (const method of ['get', 'send']) api[method] = (...args) => { const result = deferred(); requests.push({ method, args, result }); return result.promise }
  const options = load('ProblemGuidance.vue', { './problemGuidanceApi': api, './problemGuidanceData': data }).default
  const state = reactiveState({ data: { query: {}, user: { id: 1 } } })
  const page = mountLogic({ ...options,
    propsData: { problemId: '1002' },
    beforeCreate () {
      this.$route = { get query () { return state.query } }
      this.$store = { getters: { get user () { return state.user } } }
    } })
  assert.strictEqual(requests.length, 1)
  page.problemId = '1003'; await settle()
  requests[0].result.resolve(fixture()); await settle()
  assert.strictEqual(page.session, null, 'late old problem GET cannot populate new problem')
  requests[1].result.resolve(fixture('1003')); await settle()
  assert.strictEqual(page.canCompose, true)
  state.query = { from: 'learning-path', path: '7', revision: '2', step: '3' }; await settle()
  assert.strictEqual(requests.length, 2, 'return-route changes must not reset guidance')
  page.thought = '我理解输入是网格，但不确定如何区分不同的连通区域。'; page.send()
  assert.strictEqual(requests.length, 3)
  page.send(); assert.strictEqual(requests.length, 3, 'double click must not create another POST')
  const payload = requests[2].args[2]
  requests[2].result.reject(new Error('network')); await settle()
  page.retry(); assert.strictEqual(requests[3].args[2].request_id, payload.request_id, 'retry reuses idempotency key')
  page.contestId = '7'; await settle()
  requests[3].result.resolve(fixture('1003')); await settle()
  assert.strictEqual(page.session, null, 'late POST cannot cross contest context')
  requests[4].result.resolve(fixture('1003', '7')); await settle()
  assert.strictEqual(page.canCompose, false, 'contest requires explicit capability')
  page.contestId = null; await settle()
  requests[5].result.resolve({ ...fixture('1003'), status: 'waiting', available_at: new Date(Date.now() + 10000).toISOString() }); await settle()
  assert(page.timer)
  page.now += 20000
  assert.strictEqual(page.seconds, 0)
  assert.strictEqual(page.canCompose, false, 'local countdown does not grant permission')
  state.user = {}; await settle()
  assert.strictEqual(page.session, null)
  assert.strictEqual(page.timer, null)
  state.user = { id: 2 }; await settle()
  requests[6].result.resolve(fixture('1003', null, '1')); await settle()
  assert.strictEqual(page.canCompose, false, 'wrong identity is rejected')
  assert(page.error)
  const pending = page.load()
  page.$unmount()
  requests[7].result.resolve(fixture('1003', null, '2')); await pending
  assert.strictEqual(page.session, null, 'destroyed component ignores response')
}
async function apiTests () {
  for (const mock of [true, false, 'true']) {
    const calls = []
    const client = { get: (url, options) => { calls.push({ url, options }); return Promise.resolve({ data: { error: null, data: {} } }) } }
    const api = load('problemGuidanceApi.js', { axios: { create: config => { assert.strictEqual(config.baseURL, ''); return client } } }, mock).default
    await api.get(expected, 'failure')
    assert.strictEqual(calls[0].url, '/api/problem-guidance')
    assert.strictEqual(calls[0].options.params.mock_guidance, mock === true ? 'failure' : undefined)
    assert.strictEqual(calls[0].options.params.user_id, undefined, 'server infers identity')
  }
}
async function mockTests () {
  const routes = {}
  let now = Date.now()
  class Clock extends Date { constructor (...args) { super(...(args.length ? args : [now])) } static now () { return now } }
  const module = { exports: {} }
  vm.runInNewContext(fs.readFileSync(require.resolve('../build/mock-problem-guidance.js'), 'utf8'), { module, Date: Clock, setTimeout })
  let loggedIn = true
  module.exports({ get: (url, fn) => { routes['get' + url] = fn }, post: (url, fn) => { routes['post' + url] = fn } }, {
    user: { id: 1 }, isLoggedIn: () => loggedIn, problems: [{ _id: '1002' }, { _id: '1003' }], submissions: []
  })
  async function call (method, scenario, body, extra = {}) {
    let status = 200; let result
    await routes[method + '/problem-guidance' + (method === 'post' ? '/messages' : '')]({ query: { problem_id: '1002', mock_guidance: scenario, ...extra }, body }, {
      status (code) { status = code; return this }, json (value) { result = JSON.parse(JSON.stringify(value)) }
    })
    return { status, ...result }
  }
  const read = (await call('get', 'waiting')).data
  assert.strictEqual((await call('get', 'waiting')).data.available_at, read.available_at, 'refresh cannot reset waiting period')
  const thought = '我理解输入表示网格中的道路，目标是找到最少移动次数。'
  const payload = state => ({ session_id: state.session_id, request_id: 'request-1', text: thought })
  assert.strictEqual((await call('post', 'waiting', payload(read))).status, 409)
  now += 31000
  assert.strictEqual((await call('get', 'waiting')).data.status, 'ready')
  for (const scenario of ['disabled', 'exhausted', 'unknown']) {
    const state = (await call('get', scenario)).data
    assert([403, 429, 409].includes((await call('post', scenario, payload(state))).status))
  }
  const blocked = (await call('get', 'available', null, { contest_id: '7' })).data
  assert.strictEqual((await call('post', 'available', payload(blocked), { contest_id: '7' })).status, 403)
  assert.strictEqual((await call('get', 'contest-allowed', null, { contest_id: '7' })).data.capabilities.contest_allowed, true)
  const state = (await call('get', 'available')).data
  assert.strictEqual((await call('post', 'available', { ...payload(state), session_id: read.session_id })).status, 409)
  assert.strictEqual((await call('post', 'available', { ...payload(state), text: '不会' })).data.quota.remaining, 3)
  let answer = (await call('post', 'available', { ...payload(state), request_id: 'valid-1' })).data
  assert.strictEqual(answer.stage, 'knowledge')
  assert.strictEqual(answer.messages.length, 2)
  answer = (await call('post', 'available', { ...payload(state), request_id: 'valid-1' })).data
  assert.strictEqual(answer.quota.remaining, 2)
  assert.strictEqual((await call('post', 'available', { ...payload(state), request_id: 'valid-1', text: thought + '不同输入' })).status, 409)
  await call('post', 'available', { ...payload(state), request_id: 'valid-2' })
  answer = (await call('post', 'available', { ...payload(state), request_id: 'valid-3' })).data
  assert.strictEqual(answer.status, 'exhausted')
  assert.strictEqual((await call('get', 'available')).data.quota.remaining, 0)
  assert.strictEqual((await call('post', 'available', { ...payload(state), request_id: 'valid-4' })).status, 429)
  const failed = (await call('get', 'failure')).data
  assert.strictEqual((await call('post', 'failure', payload(failed))).status, 503)
  assert.strictEqual((await call('post', 'failure', payload(failed))).data.quota.remaining, 2)
  const insufficient = (await call('get', 'insufficient')).data
  assert.strictEqual((await call('post', 'insufficient', payload(insufficient))).data.status, 'ready')
  const pending = (await call('get', 'pending')).data
  const inFlight = call('post', 'pending', payload(pending))
  assert.strictEqual((await call('get', 'pending')).data.status, 'generating')
  assert.strictEqual((await call('post', 'pending', payload(pending))).data.status, 'generating')
  assert.strictEqual((await inFlight).data.quota.remaining, 2, 'concurrent retries consume only one hint')
  assert.strictEqual((await call('get', 'pending')).data.messages.length, 2)
  assert.strictEqual((await call('get', 'available', null, { problem_id: ['1002'] })).status, 400)
  assert.strictEqual((await call('get', 'available', null, { problem_id: '9999' })).status, 404)
  loggedIn = false
  assert.strictEqual((await call('get', 'available')).status, 401)
}
async function uncertainRequestRecovery () {
  const requests = []
  const api = {}
  for (const method of ['get', 'send']) api[method] = (...args) => { const result = deferred(); requests.push({ method, args, result }); return result.promise }
  const options = load('ProblemGuidance.vue', { './problemGuidanceApi': api, './problemGuidanceData': data }).default
  const page = mountLogic({ ...options,
    propsData: { problemId: '1002' },
    beforeCreate () {
      this.$route = { query: {} }
      this.$store = { getters: { user: { id: 1 } } }
    } })
  requests[0].result.resolve(fixture()); await settle()
  page.thought = '我理解输入表示网格，目标是最少移动次数，但不知道如何逐层探索。'
  page.send()
  const payload = requests[1].args[2]
  requests[1].result.reject(new Error('response lost after server accepted')); await settle()
  page.load(); requests[2].result.reject(new Error('status read offline')); await settle()
  assert.strictEqual(page.retryPayload.request_id, payload.request_id, 'a failed GET cannot discard an uncertain POST key')
  page.retry()
  assert.strictEqual(requests[3].args[2].request_id, payload.request_id, 'retry after GET failure remains idempotent')
  requests[3].result.resolve({ ...fixture(), status: 'generating' }); await settle()
  assert.strictEqual(page.retryPayload.request_id, payload.request_id, 'pending generation retains its request key')
  page.load()
  requests[4].result.resolve({ ...fixture(),
    stage: 'knowledge',
    quota: { limit: 3, remaining: 2 },
    last_request_id: payload.request_id,
    messages: [{ id: 'student-1', role: 'student', stage: 'understand', text: payload.text }, { id: 'guide-1', role: 'guide', stage: 'understand', text: '先说说终点与最短路有什么区别。' }] })
  await settle()
  assert.strictEqual(page.retryPayload, null)
  assert.strictEqual(page.thought, '', 'accepted thought must not remain in the next-stage input')
  assert.strictEqual(page.session.quota.remaining, 2)
  const before = requests.length
  page.send()
  assert.strictEqual(requests.length, before, 'recovered old input cannot create a new charged request')
  page.thought = '现在理解最短路与到达终点不同，下一步想比较不同的搜索次序。'
  page.send(); requests[before].result.reject(new Error('network')); await settle()
  page.load(); requests[before + 1].result.reject({ response: { status: 403 } }); await settle()
  assert.strictEqual(page.retryPayload, null, 'explicit permission rejection ends retry')
  assert.strictEqual(page.canCompose, false)
  page.$unmount()
  console.log('PASS: accepted POST timeout, failed GET, idempotent retry, pending generation and acknowledged input cleanup')
}
test('guidance context and lifecycle', componentTests)
test('uncertain accepted request recovery remains idempotent', uncertainRequestRecovery)
test('guidance production API query isolation', apiTests)
test('guidance mock permissions, timer and quota', mockTests, 10000)
