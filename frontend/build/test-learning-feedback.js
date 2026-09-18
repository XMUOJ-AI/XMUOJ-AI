'use strict'

// Run from frontend: node build/test-learning-feedback.js
const assert = require('assert')
const fs = require('fs')
const path = require('path')
const vm = require('vm')
const babel = require('babel-core')
const Vue = require('vue')
Vue.config.silent = true
function load (name, imports = {}, mock = true) {
  let source = fs.readFileSync(path.join(__dirname, '../src/pages/oj/views/user', name), 'utf8')
  if (name.endsWith('.vue')) source = source.match(/<script>([\s\S]*?)<\/script>/)[1]
  const code = babel.transform(source, { babelrc: false, presets: [['env', { targets: { node: 'current' } }], 'stage-2'] }).code
  const module = { exports: {} }
  vm.runInNewContext(code, { module, exports: module.exports, require: key => imports[key], process: { env: { AI_FEATURES_MOCK: mock } }, setTimeout, clearTimeout })
  return module.exports
}
const data = load('learningFeedbackData.js')
const summary = (userId = 1) => ({ user_id: userId, status: 'ready', capabilities: { can_generate: true }, range: { start: '2026-09-01T00:00:00Z', end: '2026-09-14T00:00:00Z' }, submission_count: 1, evidence: [{ id: 's1', text: '1001 · A + B · 通过', occurred_at: '2026-09-12T00:00:00Z' }] })
const feedback = (userId = 1, generationId = 'g1') => ({ user_id: userId, generation_id: generationId, status: 'ready', basis: summary(userId), overview: '样本有限', points: [{ id: 'p1', label: 'BFS', assessment: 'future', observation: '依据不足', source_ids: ['missing'] }], suggestions: [{ id: 'a1', action: '画网格练习', source_ids: ['missing'] }], sources: [] })
function deferred () {
  const task = {}
  task.promise = new Promise((resolve, reject) => { task.resolve = resolve; task.reject = reject })
  return task
}
async function flush () { await Promise.resolve(); await Vue.nextTick(); await Promise.resolve() }
async function main () {
  const normalized = data.normalizeFeedback(feedback(), 1)
  assert.strictEqual(normalized.sources[0].available, false, 'missing source must degrade visibly')
  for (const status of ['future', 'constructor', '__proto__', null, {}]) assert.strictEqual(data.assessmentLabel(status), '评估待确认')
  assert.strictEqual(data.normalizeSummary({ user_id: 1, status: 'future' }, 1).can_generate, false)
  assert.strictEqual(data.normalizeSummary({ ...summary(), capabilities: { can_generate: 'true' } }, 1).can_generate, false)
  for (const raw of [null, [], { ...summary(), user_id: 2 }, { ...summary(), evidence: [null] }, { ...summary(), evidence: {} }, { ...summary(), range: {} }]) {
    assert.throws(() => data.normalizeSummary(raw, 1), e => e.code === 'invalid_data')
  }
  for (const raw of [{ ...feedback(), points: [null] }, { ...feedback(), sources: {} }, { ...feedback(), suggestions: [] }, { ...feedback(), user_id: 2 }, { ...feedback(), generation_id: {} }]) {
    assert.throws(() => data.normalizeFeedback(raw, 1), e => e.code === 'invalid_data')
  }
  assert.throws(() => data.normalizeFeedback(feedback(), 1, 'old-job'), e => e.code === 'invalid_data')
  const unavailable = feedback()
  unavailable.sources = [{ id: 'missing', availability: 'future', excerpt: 'must not display' }]
  assert.strictEqual(data.normalizeFeedback(unavailable, 1).sources[0].excerpt, '')

  const home = load('UserHome.vue', { vuex: { mapActions: () => ({}), mapGetters: () => ({}) }, './LearningPath.vue': {}, './LearningFeedback.vue': {}, '@/utils/time': {}, '@oj/api': {} }).default
  const own = { $route: { query: { tab: 'learning-feedback', path: 'p', revision: '3', step: 's', mock_path: 'ready' } }, isOwnHome: true, user: { id: 1 } }
  home.methods.syncTab.call(own)
  assert.strictEqual(own.activeTab, 'learning-feedback')
  own.isOwnHome = false
  home.methods.syncTab.call(own)
  assert.strictEqual(own.activeTab, 'problems', 'other profiles must not restore a private feedback tab')
  let nextRoute
  own.$router = { replace: value => { nextRoute = value } }
  home.watch.activeTab.call(own, 'learning-path')
  assert.strictEqual(nextRoute.query.revision, '3')
  assert.strictEqual(nextRoute.query.step, 's')
  assert.strictEqual(nextRoute.query.mock_path, 'ready')
  const calls = []
  const client = { create: () => ({ request: options => { calls.push(options); return Promise.resolve({ data: { error: null, data: {} } }) } }) }
  for (const mock of [true, false, 'true']) {
    const api = load('learningFeedbackApi.js', { axios: client }, mock).default
    await api.summary('empty'); await api.generate('empty'); await api.result('id', 'empty')
    calls.slice(-3).forEach(call => {
      assert(call.url.startsWith('/api/learning-feedback'))
      assert.strictEqual(call.params.mock_feedback, mock === true ? 'empty' : undefined)
    })
  }
  const requests = []
  const api = {}
  for (const method of ['summary', 'generate', 'result']) {
    api[method] = (...args) => { const task = deferred(); requests.push({ method, args, task }); return task.promise }
  }
  const options = load('LearningFeedback.vue', { './learningFeedbackApi': api, './learningFeedbackData': data, '@/utils/time': {} }).default
  const state = new Vue({ data: { route: { query: {} }, user: { id: 1, username: 'mock_student' } } })
  const page = new Vue({
    ...options,
    beforeCreate () {
      Object.defineProperty(this, '$route', { get: () => state.route })
      this.$store = { getters: state, dispatch: () => {} }
      this.$router = { replace: route => { state.route = route } }
    }
  })
  const first = page.load()
  requests[0].task.resolve(summary())
  await first
  assert.strictEqual(requests.length, 1, 'initial load must not generate details')
  const generating = page.generate()
  await page.generate()
  assert.strictEqual(requests.length, 2, 'double click must not duplicate generation')
  state.route = { query: { mock_feedback: 'empty' } }
  await flush()
  requests[2].task.resolve({ user_id: 1, status: 'empty' })
  await flush()
  requests[1].task.resolve(feedback())
  await generating
  assert.strictEqual(page.feedback, null, 'old generation must not overwrite new scenario')
  assert.strictEqual(page.summary.status, 'empty')
  state.route = { query: {} }
  await flush()
  requests[3].task.resolve(summary())
  await flush()
  const next = page.generate()
  requests[4].task.resolve({ user_id: 1, generation_id: 'g1', status: 'generating' })
  await next
  const checking = page.checkResult()
  state.user = { id: 2, username: 'second' }
  await flush()
  requests[6].task.resolve(summary(2))
  await flush()
  requests[5].task.resolve(feedback())
  await checking
  assert.strictEqual(page.feedback, null, 'poll result for old user must be ignored')
  assert.strictEqual(page.summary.status, 'ready')
  const denied = page.generate()
  requests[7].task.reject({ response: { status: 401 } })
  await denied
  assert.strictEqual(page.error.action, 'login')
  assert.strictEqual(page.summary, null, 'expired session must clear private content')
  const restoring = page.load()
  requests[8].task.resolve(summary(2))
  await restoring
  const late = page.generate()
  page.$destroy()
  requests[9].task.resolve(feedback(2))
  await late
  assert.strictEqual(page.feedback, null, 'destroyed tab must not apply pending generation')
  state.$destroy()

  const handlers = {}
  let loggedIn = true
  const context = { user: { id: 1 }, isLoggedIn: () => loggedIn, problems: [{ _id: '1001', title: 'A + B' }], submissions: [{ id: 's1', user_id: 1, problem_id: '1001', create_time: new Date().toISOString(), result: 0 }] }
  require('./mock-learning-feedback')({ get: (url, handler) => { handlers['get ' + url] = handler }, post: (url, handler) => { handlers['post ' + url] = handler } }, context)
  function request (method, url, mode, generationId) {
    let status = 200
    let body
    const res = { status: value => { status = value; return res }, json: value => { body = value } }
    handlers[method + ' ' + url]({ query: { mock_feedback: mode }, params: { id: generationId } }, res)
    return { status, body }
  }
  assert.strictEqual(request('get', '/learning-feedback', 'empty').body.data.status, 'empty')
  assert.strictEqual(request('post', '/learning-feedback/generations', 'disabled').status, 403)
  assert.strictEqual(request('post', '/learning-feedback/generations', 'busy').status, 429)
  const job = request('post', '/learning-feedback/generations', 'ready').body.data
  assert.strictEqual(job.user_id, 1)
  assert.strictEqual(job.status, 'generating')
  assert.strictEqual(request('get', '/learning-feedback/generations/:id', 'empty', job.generation_id).status, 404)
  const scenarios = ['ready', 'insufficient', 'failed', 'retry', 'unknown', 'unavailable', 'invalid', 'generating']
  const scenarioJobs = scenarios.map(mode => request('post', '/learning-feedback/generations', mode).body.data)
  await new Promise(resolve => setTimeout(resolve, 1300))
  scenarioJobs.forEach((item, index) => {
    const mode = scenarios[index]
    const raw = request('get', '/learning-feedback/generations/:id', mode, item.generation_id).body.data
    if (mode === 'invalid') assert.throws(() => data.normalizeFeedback(raw, 1), e => e.code === 'invalid_data')
    else {
      const adapted = data.normalizeFeedback(raw, 1)
      assert.strictEqual(adapted.status, { insufficient: 'insufficient', failed: 'failed', retry: 'failed', unknown: 'unknown', generating: 'generating' }[mode] || 'ready')
      if (mode === 'unavailable') assert(adapted.sources.every(source => !source.available))
    }
  })
  const retry = request('post', '/learning-feedback/generations', 'retry').body.data
  await new Promise(resolve => setTimeout(resolve, 1300))
  assert.strictEqual(request('get', '/learning-feedback/generations/:id', 'retry', retry.generation_id).body.data.status, 'ready')
  context.submissions[0].result = 'constructor'
  assert(request('get', '/learning-feedback', 'ready').body.data.evidence[0].text.includes('评测状态待确认'))
  context.submissions[0].result = -2
  assert(request('get', '/learning-feedback', 'ready').body.data.evidence[0].text.includes('编译错误'))
  loggedIn = false
  assert.strictEqual(request('get', '/learning-feedback/generations/:id', 'ready', job.generation_id).status, 401)
  console.log('PASS: malformed payloads, identity/task checks, missing sources, unknown states, production query isolation, explicit generation, duplicate clicks, scenario/user/destroy races, expired session, mock authorization')
}
main().catch(error => { console.error(error); process.exitCode = 1 })
