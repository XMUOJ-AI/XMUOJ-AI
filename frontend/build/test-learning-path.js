'use strict'

// Run from frontend: node build/test-learning-path.js
const assert = require('assert')
const fs = require('fs')
const path = require('path')
const vm = require('vm')
const Vue = require('vue')
const babel = require('babel-core')
Vue.config.silent = true
function load (filename, imports) {
  let source = fs.readFileSync(path.join(__dirname, '../src/pages/oj/views/user', filename), 'utf8')
  if (filename.endsWith('.vue')) source = source.match(/<script>([\s\S]*?)<\/script>/)[1]
  const code = babel.transform(source, { babelrc: false, presets: [['env', { targets: { node: 'current' } }], 'stage-2'] }).code
  const module = { exports: {} }
  vm.runInNewContext(code, { module, exports: module.exports, require: name => imports[name], process, setTimeout, clearTimeout })
  return module.exports
}
const data = load('learningPathData.js', {})
const fixture = (revision = 1) => ({
  status: 'ready',
  path_id: 7,
  revision,
  next_step_id: '1',
  next_problem_id: '20',
  steps: [{ step_id: 1,
    status: 'pending',
    problems: [
    { problem_id: 10, display_id: 1001, availability: 'available', context: { type: 'public' } },
    { problem_id: 20, display_id: '1002', availability: 'available', context: { type: 'contest', contest_id: 3 } }
    ] }]
})
const reply = data => ({ data: { data } })
function deferred () {
  const result = {}
  result.promise = new Promise(resolve => { result.resolve = resolve })
  return result
}
const normalized = data.normalizePath(fixture())
assert.strictEqual(normalized.path_id, '7')
assert.strictEqual(normalized.steps[0].problems.length, 2)
assert.strictEqual(normalized.steps[0].problems[1].context.contest_id, '3')
assert.strictEqual(normalized.evidence.length, 0)
assert.strictEqual(data.statusLabel('new_status'), '状态待确认')
assert.strictEqual(data.assessmentLabel('mastered'), '已掌握')
assert.strictEqual(data.assessmentLabel('new_assessment'), '评估待确认')
for (const corrupt of [p => { p.steps[0] = null }, p => { p.next_problem_id = 99 }, p => { p.steps.push(p.steps[0]) }]) {
  const bad = fixture()
  corrupt(bad)
  assert.throws(() => data.normalizePath(bad), e => e.code === 'invalid_data')
}
const unsupported = fixture()
unsupported.steps[0].problems[0].context.type = 'future_context'
assert.strictEqual(data.normalizePath(unsupported).steps[0].problems[0].availability, 'unavailable')
for (const [status, action] of [[401, 'login'], [410, 'latest'], [409, 'latest'], [403, null], [429, 'retry'], [503, 'retry']]) {
  assert.strictEqual(data.errorFeedback({ response: { status } }).action, action)
}
assert.strictEqual(data.errorFeedback({ code: 'version_expired', status: 200 }).action, 'latest')
assert.strictEqual(data.errorFeedback(new Error('network')).action, 'retry')

async function main () {
  const requests = []
  const explanation = deferred()
  const api = {
    getLearningPath (params) {
      const result = deferred()
      requests.push({ params, result })
      return result.promise
    },
    explainLearningStep () { return explanation.promise }
  }
  const options = load('LearningPath.vue', { '@oj/api': api, '@/utils/time': {}, './learningPathData': data }).default
  const route = new Vue({ data: { current: { query: { path: '7', revision: '1' } } } })
  let navigation
  const page = new Vue({
    ...options,
    beforeCreate () {
      this.$store = { getters: { user: { id: 1 } } }
      Object.defineProperty(this, '$route', { get: () => route.current })
      this.$router = {
        // Callback-only router deliberately returns undefined.
        replace: (location, done) => { route.current = location; if (done) done() },
        push: location => { navigation = location }
      }
    }
  })
  const first = page.load()
  requests[0].result.resolve(reply(fixture()))
  await first
  assert.strictEqual(page.path.revision, '1')
  const explaining = page.explain(page.path.steps[0])
  const oldRefresh = page.load()
  page.acceptPath(data.normalizePath(fixture(2)))
  await Vue.nextTick()
  assert.strictEqual(requests.length, 3)
  assert.strictEqual(requests[2].params.revision, '2')
  requests[2].result.resolve(reply(fixture(2)))
  await Promise.resolve()
  await Vue.nextTick()
  requests[1].result.resolve(reply(fixture(1)))
  await oldRefresh
  assert.strictEqual(page.path.revision, '2', 'late old refresh must not overwrite the accepted version')
  explanation.resolve(reply({ path_id: 7, revision: 1, step_id: 1, status: 'ready', text: 'old explanation' }))
  await explaining
  assert.strictEqual(Object.keys(page.explanations).length, 0)
  const count = requests.length
  route.current = { query: { path: '7', revision: '2', step: '1' } }
  await Vue.nextTick()
  assert.strictEqual(requests.length, count, 'step-only navigation must not refetch')
  route.current = { query: { path: '7', revision: '3' } }
  await Vue.nextTick()
  assert.strictEqual(requests.length, count + 1)
  requests[count].result.resolve(reply(fixture(2)))
  await Promise.resolve()
  await Vue.nextTick()
  assert.strictEqual(page.error.action, 'latest', 'mismatched response must not be applied')
  page.handleError(page.error)
  await Vue.nextTick()
  assert.strictEqual(requests[requests.length - 1].params.revision, null)
  requests[requests.length - 1].result.resolve(reply(fixture(3)))
  await Promise.resolve()
  await Vue.nextTick()
  const step = page.path.steps[0]
  await page.start(step, step.problems[1])
  assert.strictEqual(navigation.name, 'contest-problem-details')
  assert.strictEqual(navigation.params.contestID, '3')
  assert.strictEqual(navigation.query.revision, '3')
  page.$destroy()
  route.$destroy()
  console.log('PASS: data adaptation, unknown states, error actions, version race, stale explanation, reactive route changes, callback navigation')
}

async function accountIsolation () {
  const state = new Vue({ data: { user: { id: 1 }, query: { path: '7', revision: '1', step: '1' } } })
  const requests = []
  const explanations = []
  const api = {
    getLearningPath (params) { const result = deferred(); requests.push({ params, result }); return result.promise },
    explainLearningStep () { const result = deferred(); explanations.push(result); return result.promise }
  }
  const options = load('LearningPath.vue', { '@oj/api': api, '@/utils/time': {}, './learningPathData': data }).default
  const page = new Vue({ ...options,
    beforeCreate () {
      this.$store = { getters: { get user () { return state.user } } }
      this.$route = { get query () { return state.query } }
      this.$router = { replace: (location, done) => { state.query = location.query; if (done) done() } }
    } })
  const settle = async () => { await Vue.nextTick(); await Promise.resolve(); await Vue.nextTick() }
  const initial = page.load()
  requests[0].result.resolve(reply(fixture())); await initial
  page.showEvidence = true
  const explaining = page.explain(page.path.steps[0])
  const staleRefresh = page.load()
  state.user = { id: 2 }
  // Resolve before the Vue watcher flushes: the request itself must check identity.
  requests[1].result.resolve(reply({ ...fixture(), summary: 'old-account-data' }))
  explanations[0].resolve(reply({ path_id: 7, revision: 1, step_id: 1, status: 'ready', text: 'old-account-explanation' }))
  await staleRefresh; await explaining; await settle()
  assert.strictEqual(page.path, null, 'account change clears private path')
  assert.strictEqual(Object.keys(page.explanations).length, 0)
  assert.strictEqual(page.showEvidence, false)
  assert.strictEqual(state.query.path, undefined, 'old account route identifiers must be removed')
  assert.strictEqual(state.query.revision, undefined)
  assert.strictEqual(state.query.step, undefined)
  assert.strictEqual(requests.length, 3, 'fetch the new account once after clearing the route')
  assert.strictEqual(requests[2].params.path_id, null)
  requests[2].result.resolve(reply({ ...fixture(), path_id: 'account-2-path' })); await settle()
  assert.strictEqual(page.path.path_id, 'account-2-path')
  const staleLogout = page.load()
  state.user = {}
  requests[3].result.resolve(reply({ ...fixture(), path_id: 'account-2-path' }))
  await staleLogout; await settle()
  assert.strictEqual(page.path, null)
  assert.strictEqual(page.error.action, 'login')
  assert.strictEqual(requests.length, 4, 'logout must not request a private path')
  state.user = { id: 3 }; await settle()
  assert.strictEqual(requests.length, 5)
  page.$destroy()
  requests[4].result.resolve(reply({ ...fixture(), path_id: 'account-3-path' })); await settle()
  assert.strictEqual(page.path, null, 'destroyed component ignores late account response')
  state.$destroy()
  console.log('PASS: account switch/logout clear private state, route identifiers and stale path/explanation requests')
}

async function profileLoadingAndStepOnlyRoute () {
  const state = new Vue({ data: { user: {}, query: { path: '7', revision: '1', step: '1' } } })
  const requests = []
  const api = { getLearningPath (params) { requests.push(params); return Promise.resolve(reply(fixture())) } }
  const options = load('LearningPath.vue', { '@oj/api': api, '@/utils/time': {}, './learningPathData': data }).default
  const page = new Vue({ ...options,
    beforeCreate () {
      this.$store = { getters: { get user () { return state.user } } }
      this.$route = { get query () { return state.query } }
      this.$router = { replace: (location, done) => { state.query = location.query; if (done) done() } }
    } })
  const settle = async () => { await Vue.nextTick(); await Promise.resolve(); await Vue.nextTick(); await Promise.resolve() }
  await page.load()
  assert.strictEqual(requests.length, 0)
  state.user = { id: 1 }; await settle()
  assert.strictEqual(requests[0].path_id, '7', 'initial profile loading preserves a valid return link')
  state.query = { step: '1' }; await settle()
  const count = requests.length
  state.user = { id: 2 }; await settle()
  assert.strictEqual(state.query.step, undefined)
  assert.strictEqual(requests.length, count + 1, 'account switch with only a step query still fetches once')
  assert.strictEqual(requests[count].path_id, null)
  page.$destroy(); state.$destroy()
  console.log('PASS: initial profile preserves deep links; step-only account switch still refreshes')
}
main().then(accountIsolation).then(profileLoadingAndStepOnlyRoute).catch(error => { console.error(error); process.exitCode = 1 })
