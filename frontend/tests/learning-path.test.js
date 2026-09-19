import assert from 'node:assert'
import { createRequire } from 'node:module'
import { nextTick } from 'vue'
import { flushPromises } from '@vue/test-utils'
import { mountLogic, reactiveState } from './componentHarness'
import { beforeEach, test, vi } from 'vitest'
import Component from '../src/pages/oj/views/user/LearningPath.vue'
import * as data from '../src/pages/oj/views/user/learningPathData.js'
const require = createRequire(import.meta.url)
const injected = vi.hoisted(() => ({ api: {}, axios: {} }))
vi.mock('@oj/api', () => ({ default: new Proxy({}, { get: (_, key) => (...args) => injected.api[key](...args) }) }))
vi.mock('axios', () => ({ default: { create: config => new Proxy(options => injected.axios.create(config)(options), { get: (_, key) => (...args) => injected.axios.create(config)[key](...args) }) } }))
beforeEach(() => { globalThis.__AI_FEATURES_MOCK__ = true; globalThis.__LEARNING_PATH_MOCK__ = true })
function load (filename, imports = {}, mock = true) {
  globalThis.__AI_FEATURES_MOCK__ = mock
  if (imports.axios) injected.axios = imports.axios
  if (imports['@oj/api']) injected.api = imports['@oj/api']
  if (filename === 'LearningPath.vue') return { default: Component }
  if (filename === 'learningPathData.js') return data


  throw new Error('Unexpected test module: ' + filename)
}

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
  const route = reactiveState({ data: { current: { query: { path: '7', revision: '1' } } } })
  let navigation
  const page = mountLogic({
    ...options,
    beforeCreate () {
      this.$store = { getters: { user: { id: 1 } } }
      Object.defineProperty(this, '$route', { get: () => route.current })
      this.$router = {
        // Router 4 navigation is Promise-based.
        replace: location => { route.current = location; return Promise.resolve() },
        push: location => { navigation = location; return Promise.resolve() }
      }
    }
  })
  const first = flushPromises()
  requests[0].result.resolve(reply(fixture()))
  await first
  assert.strictEqual(page.path.revision, '1')
  const explaining = page.explain(page.path.steps[0])
  const oldRefresh = page.load()
  page.acceptPath(data.normalizePath(fixture(2)))
  await nextTick()
  assert.strictEqual(requests.length, 3)
  assert.strictEqual(requests[2].params.revision, '2')
  requests[2].result.resolve(reply(fixture(2)))
  await Promise.resolve()
  await nextTick()
  requests[1].result.resolve(reply(fixture(1)))
  await oldRefresh
  assert.strictEqual(page.path.revision, '2', 'late old refresh must not overwrite the accepted version')
  explanation.resolve(reply({ path_id: 7, revision: 1, step_id: 1, status: 'ready', text: 'old explanation' }))
  await explaining
  assert.strictEqual(Object.keys(page.explanations).length, 0)
  const count = requests.length
  route.current = { query: { path: '7', revision: '2', step: '1' } }
  await nextTick()
  assert.strictEqual(requests.length, count, 'step-only navigation must not refetch')
  route.current = { query: { path: '7', revision: '3' } }
  await nextTick()
  assert.strictEqual(requests.length, count + 1)
  requests[count].result.resolve(reply(fixture(2)))
  await Promise.resolve()
  await nextTick()
  assert.strictEqual(page.error.action, 'latest', 'mismatched response must not be applied')
  page.handleError(page.error)
  await nextTick()
  assert.strictEqual(requests[requests.length - 1].params.revision, null)
  requests[requests.length - 1].result.resolve(reply(fixture(3)))
  await Promise.resolve()
  await nextTick()
  const step = page.path.steps[0]
  await page.start(step, step.problems[1])
  assert.strictEqual(navigation.name, 'contest-problem-details')
  assert.strictEqual(navigation.params.contestID, '3')
  assert.strictEqual(navigation.query.revision, '3')
  page.$unmount()
  route.$unmount()
  console.log('PASS: data adaptation, unknown states, error actions, version race, stale explanation, reactive route changes, Promise navigation')
}

async function accountIsolation () {
  const state = reactiveState({ data: { user: { id: 1 }, query: { path: '7', revision: '1', step: '1' } } })
  const requests = []
  const explanations = []
  const api = {
    getLearningPath (params) { const result = deferred(); requests.push({ params, result }); return result.promise },
    explainLearningStep () { const result = deferred(); explanations.push(result); return result.promise }
  }
  const options = load('LearningPath.vue', { '@oj/api': api, '@/utils/time': {}, './learningPathData': data }).default
  const page = mountLogic({ ...options,
    beforeCreate () {
      this.$store = { getters: { get user () { return state.user } } }
      this.$route = { get query () { return state.query } }
      this.$router = { replace: location => { state.query = location.query; return Promise.resolve() } }
    } })
  const settle = async () => { await nextTick(); await Promise.resolve(); await nextTick() }
  const initial = flushPromises()
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
  page.$unmount()
  requests[4].result.resolve(reply({ ...fixture(), path_id: 'account-3-path' })); await settle()
  assert.strictEqual(page.path, null, 'destroyed component ignores late account response')
  state.$unmount()
  console.log('PASS: account switch/logout clear private state, route identifiers and stale path/explanation requests')
}

async function profileLoadingAndStepOnlyRoute () {
  const state = reactiveState({ data: { user: {}, query: { path: '7', revision: '1', step: '1' } } })
  const requests = []
  const api = { getLearningPath (params) { requests.push(params); return Promise.resolve(reply(fixture())) } }
  const options = load('LearningPath.vue', { '@oj/api': api, '@/utils/time': {}, './learningPathData': data }).default
  const page = mountLogic({ ...options,
    beforeCreate () {
      this.$store = { getters: { get user () { return state.user } } }
      this.$route = { get query () { return state.query } }
      this.$router = { replace: location => { state.query = location.query; return Promise.resolve() } }
    } })
  const settle = async () => { await nextTick(); await Promise.resolve(); await nextTick(); await Promise.resolve() }
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
  page.$unmount(); state.$unmount()
  console.log('PASS: initial profile preserves deep links; step-only account switch still refreshes')
}
test('learning path data and version/request races', main)
test('account isolation and logout preserve privacy', accountIsolation)
test('initial login and step-only deep links', profileLoadingAndStepOnlyRoute)
