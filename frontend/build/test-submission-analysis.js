'use strict'

// node build/test-submission-analysis.js — no server, database or extra dependencies.
const assert = require('assert')
const fs = require('fs')
const path = require('path')
const Module = require('module')
const babel = require('babel-core')
const Vue = require('vue')
const compiler = require('vue-template-compiler')
const directory = path.resolve(__dirname, '../src/pages/oj/views/submission')
function load (name, replacements, mock) {
  const filename = path.join(directory, name)
  let source = fs.readFileSync(filename, 'utf8')
  if (name.endsWith('.vue')) {
    const parsed = compiler.parseComponent(source)
    assert.deepStrictEqual(compiler.compile(parsed.template.content).errors, [])
    source = parsed.script.content
  }
  source = source.replace(/process.env.AI_FEATURES_MOCK/g, mock ? 'true' : 'false')
  const compiled = babel.transform(source, {babelrc: false, presets: [['env', {targets: {node: 'current'}}], 'stage-2']}).code
  const loaded = new Module(filename, module)
  loaded.filename = filename
  loaded.paths = Module._nodeModulePaths(directory)
  const original = loaded.require.bind(loaded)
  loaded.require = name => Object.prototype.hasOwnProperty.call(replacements || {}, name) ? replacements[name] : original(name)
  loaded._compile(compiled, filename)
  return loaded.exports
}
const data = load('submissionAnalysisData.js')
const replacements = {'./submissionAnalysisData': data}
const identity = {submission_id: 's-1', user_id: 1, judge_result: 0, analysis_version: data.ANALYSIS_VERSION, judge_revision: 'r1'}
const payload = Object.assign({}, identity, {capability: 'allowed', status: 'ready', summary: '参考解读', scope: {start_line: 1, end_line: 3, total_lines: 3, truncated: false}, sections: [{title: '思路', body: '分析', evidence: '代码第 1 行'}]})
const submission = {id: 's-1', user_id: 1, result: 0, code: 'code'}
function invalid (override) { assert.throws(() => data.normalizeAnalysis(Object.assign({}, payload, override), identity), /invalid_response/) }

async function run () {
  assert.strictEqual(data.localState(submission, 1), 'idle')
  assert.strictEqual(data.localState(submission, 2), 'forbidden')
  assert.strictEqual(data.localState(submission, null), 'login_required')
  assert.strictEqual(data.localState(Object.assign({}, submission, {result: -2}), 1), 'compile_error')
  assert.strictEqual(data.localState(Object.assign({}, submission, {result: 7}), 1), 'pending')
  assert.strictEqual(data.localState(Object.assign({}, submission, {result: 999}), 1), 'unavailable')
  assert.strictEqual(data.sameId({}, '[object Object]'), false)
  assert.strictEqual(data.normalizeCapability(Object.assign({}, payload, {capability: true}), identity).state, 'unavailable')
  for (const override of [{user_id: 2}, {submission_id: 's-2'}, {judge_result: -1}, {judge_revision: 'r2'}, {analysis_version: 'v2'}, {sections: {}}, {sections: [null]}, {scope: {start_line: 1, end_line: 2, total_lines: 3, truncated: false}}]) invalid(override)
  assert.strictEqual(data.normalizeAnalysis(payload, identity).state, 'ready')
  assert.strictEqual(data.normalizeAnalysis(Object.assign({}, payload, {status: 'future'}), identity).state, 'unavailable')
  assert.strictEqual(data.errorState({response: {status: 401}}), 'login_required')
  assert.strictEqual(data.errorState({code: 'quota_exceeded', response: {status: 429}}), 'quota_exceeded')
  assert.strictEqual(data.errorState({message: 'toString'}), 'failed')
  console.log('PASS identity, permission, verdict, response shape, scope and version boundaries')

  let requests = []
  const fakeAxios = {create: () => options => { requests.push(options); return Promise.resolve({data: {error: null, data: payload}}) }}
  const apiModule = load('submissionAnalysisApi.js', Object.assign({}, replacements, {axios: fakeAxios}))
  await apiModule.default.capability('s-1', 'busy')
  await apiModule.default.generate(identity, 'busy')
  assert.deepStrictEqual(requests.map(r => r.url), ['/api/submission-analysis', '/api/submission-analysis/generate'])
  assert(requests.every(r => !Object.prototype.hasOwnProperty.call(r.params, 'mock_analysis')))
  const mockApi = load('submissionAnalysisApi.js', Object.assign({}, replacements, {axios: fakeAxios}), true)
  assert.strictEqual(mockApi.analysisParams('s-1', 'busy').mock_analysis, 'busy')
  console.log('PASS absolute API paths and production mock-parameter isolation')

  requests = []
  const deferredApi = {}
  for (const method of ['capability', 'generate']) deferredApi[method] = () => new Promise((resolve, reject) => requests.push({method, resolve, reject}))
  const component = load('SubmissionAnalysis.vue', Object.assign({}, replacements, {'./submissionAnalysisApi': deferredApi, iview: {Collapse: {}, Panel: {}}}), true).default
  const store = new Vue({data: {getters: {user: {id: 1}}}})
  const route = new Vue({data: {params: {id: 's-1'}, query: {}}})
  const C = Vue.extend(component)
  const vm = new C({propsData: {submission}, beforeCreate () { this.$store = store; this.$route = route }})
  const flush = async () => { await Vue.nextTick(); await Promise.resolve(); await Promise.resolve() }
  assert.strictEqual(requests.length, 1)
  assert.strictEqual(requests[0].method, 'capability')
  requests[0].resolve(payload)
  await flush()
  assert.strictEqual(vm.state, 'idle')
  vm.generate()
  vm.generate()
  assert.strictEqual(requests.length, 2)
  vm.submission = Object.assign({}, submission, {id: 's-2'})
  route.params.id = 's-2'
  requests[1].resolve(payload)
  await flush()
  assert.strictEqual(vm.result, null)
  assert.strictEqual(vm.state, 'checking')
  const secondPayload = Object.assign({}, payload, {submission_id: 's-2'})
  requests[2].resolve(secondPayload)
  await flush()
  vm.generate()
  requests[3].resolve(secondPayload)
  await flush()
  assert.strictEqual(vm.state, 'ready')
  vm.expanded = []
  vm.expanded = ['analysis']
  await flush()
  assert.strictEqual(requests.length, 4)
  vm.submission = Object.assign({}, vm.submission, {result: -1})
  await flush()
  assert.strictEqual(vm.result, null)
  const stale = requests[4]
  store.getters.user.id = 2
  stale.resolve(Object.assign({}, secondPayload, {judge_result: -1}))
  await flush()
  assert.strictEqual(vm.state, 'forbidden')
  assert.strictEqual(vm.result, null)
  store.getters.user.id = 1
  await flush()
  const firstRetry = requests[5]
  vm.checkCapability()
  const lastRetry = requests[6]
  lastRetry.resolve(Object.assign({}, secondPayload, {judge_result: -1}))
  await flush()
  firstRetry.reject(new Error('failed'))
  await flush()
  assert.strictEqual(vm.state, 'idle')
  vm.generate()
  store.getters.user.id = null
  requests[7].resolve(Object.assign({}, secondPayload, {judge_result: -1}))
  await flush()
  assert.strictEqual(vm.state, 'login_required')
  assert.strictEqual(vm.result, null)
  vm.$destroy()
  console.log('PASS Vue lifecycle: click-only generation, duplicate click, collapse cache, route/account/rejudge reset and stale retry isolation')

  const handlers = {}
  const context = {user: {id: 1, username: 'student'}, isLoggedIn: () => loggedIn, problems: [{id: 1, _id: '1001', title: 'A+B'}], submissions: [{id: 'mock-001', user_id: 1, result: 0, code: 'original'}]}
  let loggedIn = true
  const original = JSON.stringify(context.submissions[0])
  require('./mock-submission-analysis')({get: (url, fn) => { handlers['get ' + url] = fn }, post: (url, fn) => { handlers['post ' + url] = fn }}, context)
  assert.strictEqual(JSON.stringify(context.submissions[0]), original)
  const call = (method, query, body) => new Promise(resolve => {
    const res = {statusCode: 200, status (code) { this.statusCode = code; return this }, json (value) { resolve({status: this.statusCode, body: value}) }}
    handlers[method + ' /submission-analysis' + (method === 'post' ? '/generate' : '')]({query, body}, res)
  })
  const capability = async id => (await call('get', {submission_id: id})).body.data
  for (const id of ['mock-ac', 'mock-wa', 'mock-tle', 'mock-re']) {
    const cap = await capability(id)
    const response = await call('post', {}, cap)
    assert.strictEqual(data.normalizeAnalysis(response.body.data, cap).state, 'ready')
  }
  const cap = await capability('mock-ac')
  assert.strictEqual((await call('post', {}, Object.assign({}, cap, {submission_id: 'unknown'}))).status, 404)
  assert.strictEqual((await call('post', {}, Object.assign({}, cap, {submission_id: 'mock-other'}))).status, 403)
  assert.strictEqual((await call('post', {}, Object.assign({}, cap, {user_id: 2}))).status, 409)
  for (const id of ['mock-ce', 'mock-pending']) assert.strictEqual((await call('post', {}, await capability(id))).status, 403)
  for (const scenario of ['busy', 'quota', 'failed', 'expired', 'forbidden']) assert((await call('post', {mock_analysis: scenario}, cap)).status >= 400)
  const clipped = await call('post', {mock_analysis: 'truncated'}, cap)
  assert.strictEqual(data.normalizeAnalysis(clipped.body.data, cap).result.scope.truncated, true)
  for (const scenario of ['mismatch', 'malformed', 'version']) {
    const response = await call('post', {mock_analysis: scenario}, cap)
    assert.throws(() => data.normalizeAnalysis(response.body.data, cap), /invalid_response/)
  }
  assert.strictEqual((await call('post', {mock_analysis: 'unknown'}, cap)).body.data.status, 'future_state')
  assert.strictEqual((await call('post', {}, await capability('mock-001'))).body.data.status, 'insufficient_evidence')
  context.submissions.find(s => s.id === 'mock-ac').result = -1
  assert.strictEqual((await call('post', {}, cap)).status, 409)
  loggedIn = false
  assert.strictEqual((await call('post', {}, cap)).status, 401)
  console.log('PASS mock ownership/login enforcement, verdict branches, unknown submissions, revision conflicts, truncation and failure scenarios')
}
run().catch(error => { console.error(error); process.exitCode = 1 })
