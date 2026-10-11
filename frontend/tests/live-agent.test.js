import { beforeEach, expect, test, vi } from 'vitest'
import { nextTick } from 'vue'
import { mount, flushPromises } from '@vue/test-utils'
import { mountLogic, reactiveState } from './componentHarness'
const transport = vi.hoisted(() => vi.fn())
vi.mock('axios', () => ({ default: { create: () => transport } }))
vi.mock('@oj/api', () => ({ default: {} }))
import { requestKey, runAgent, startConversation } from '../src/api/agent'
import { getCurrentPath, refreshPath, validatePath } from '../src/pages/oj/views/user/learningPathApi'
import AgentRun from '../src/pages/oj/components/AgentRun.vue'
import LivePath from '../src/pages/oj/views/user/LiveLearningPath.vue'
import LiveGuidance from '../src/pages/oj/views/problem/LiveProblemGuidance.vue'
import LiveAnalysis from '../src/pages/oj/views/submission/LiveSubmissionAnalysis.vue'
import PrototypePath from '../src/pages/oj/views/user/LearningPath.vue'
import PrototypeGuidance from '../src/pages/oj/views/problem/ProblemGuidance.vue'
import PrototypeAnalysis from '../src/pages/oj/views/submission/SubmissionAnalysis.vue'
import Feedback from '../src/pages/oj/views/user/LearningFeedback.vue'
const result = { summary: '代码说明', sections: [{ title: '求和', explanation: '累加输入', code_refs: ['L1'] }], complexity: { time: 'O(n)', space: 'O(1)', assumptions: [] }, improvement_directions: [], contains_full_solution: false }
const request = { service_type: 'code_explanation', submission_id: 'submission-1' }
const reply = data => ({ status: 200, data: { error: null, data } })
const run = (status, extra = {}) => ({ run_id: 'run-1', service_type: 'code_explanation', status, result: status === 'succeeded' ? result : null, ...extra })
const path = { path_id: 'path-1', status: 'active', target: null, steps: [{ order: 1, knowledge_code: 'basic', knowledge_name: '基础', problem_id: '1002', title: '练习', reason_text: '巩固基础', status: 'pending' }] }
const deferred = () => { let resolve; const promise = new Promise(r => { resolve = r }); return { resolve, promise } }
function context () { return { store: reactiveState({ data: { getters: { user: { id: 1 } } } }), route: reactiveState({ data: { params: { id: 'submission-1' }, query: {} } }), router: { replace: vi.fn(() => Promise.resolve()) } } }
function logic (component, propsData, ctx = context()) { return mountLogic({ ...component, propsData, beforeCreate () { this.$store = ctx.store; this.$route = ctx.route; this.$router = ctx.router } }) }
beforeEach(() => { transport.mockReset(); globalThis.__AI_FEATURES_MOCK__ = false; globalThis.__LEARNING_PATH_MOCK__ = false })
test('real endpoints accept display IDs and exact run body', async () => {
  transport.mockResolvedValueOnce(reply({ conversation_id: 'c1' })); await startConversation('1002')
  expect(transport.mock.calls[0][0]).toMatchObject({ method: 'post', url: 'agent/v1/conversations', data: { problem_id: '1002', service_type: 'socratic_hint' } })
  transport.mockResolvedValueOnce(reply(run('queued'))).mockResolvedValueOnce(reply(run('succeeded')))
  await expect(runAgent(request, { key: 'key-1' }, { wait: () => Promise.resolve() })).resolves.toMatchObject({ result })
  expect(transport.mock.calls[1][0]).toEqual({ method: 'post', url: 'agent/v1/runs', data: { ...request, options: { language: 'zh-CN', detail_level: 'normal' } }, headers: { 'Idempotency-Key': 'key-1' } })
  expect(transport.mock.calls[2][0]).toMatchObject({ method: 'get', url: 'agent/v1/runs/run-1' })
})
test('uncertain POST keeps key and paused polling resumes the same run', async () => {
  const attempt = {}; transport.mockRejectedValueOnce(new Error('network')).mockResolvedValueOnce(reply(run('queued')))
  await expect(runAgent(request, attempt)).rejects.toThrow('network'); const key = attempt.key
  await expect(runAgent(request, attempt, { maxPolls: 0 })).rejects.toMatchObject({ code: 'AGENT_POLL_PAUSED' })
  expect(transport.mock.calls[1][0].headers['Idempotency-Key']).toBe(key)
  transport.mockResolvedValueOnce(reply(run('succeeded'))); await runAgent(request, attempt)
  expect(transport.mock.calls[2][0].method).toBe('get')
})
test('polls are bounded and mismatched run/result identities rejected', async () => {
  transport.mockResolvedValue(reply(run('queued')))
  await expect(runAgent(request, {}, { maxPolls: 2, wait: () => Promise.resolve() })).rejects.toMatchObject({ code: 'AGENT_POLL_PAUSED' })
  expect(transport).toHaveBeenCalledTimes(3)
  transport.mockResolvedValueOnce(reply(run('succeeded', { service_type: 'socratic_hint' })))
  await expect(runAgent(request, {})).rejects.toMatchObject({ code: 'AGENT_INVALID_RESPONSE' })
  transport.mockResolvedValueOnce(reply(run('succeeded', { service_type: 'learning_path_explanation', result: { path_id: 'other', contains_full_solution: false } })))
  await expect(runAgent({ service_type: 'learning_path_explanation', path_id: 'p1' }, {})).rejects.toMatchObject({ code: 'AGENT_INVALID_RESPONSE' })
})
test('context cancellation stops the next poll', async () => {
  let active = true; transport.mockResolvedValueOnce(reply(run('queued')))
  await expect(runAgent(request, {}, { current: () => active, wait: async () => { active = false } })).rejects.toMatchObject({ code: 'AGENT_CANCELLED' })
  expect(transport).toHaveBeenCalledTimes(1)
})
test('backend configuration and terminal failure messages are preserved', async () => {
  transport.mockRejectedValueOnce({ response: { status: 503, data: { error: 'AGENT_DEPENDENCY_NOT_READY', data: { message: '模型服务尚未配置' } } } })
  await expect(runAgent(request, {})).rejects.toMatchObject({ code: 'AGENT_DEPENDENCY_NOT_READY', message: '模型服务尚未配置', status: 503 })
  transport.mockResolvedValueOnce(reply(run('failed', { error_detail: { code: 'AGENT_OUTPUT_SCHEMA_INVALID', message: '模型输出无法使用' } })))
  await expect(runAgent(request, {})).rejects.toMatchObject({ terminal: true, message: '模型输出无法使用' })
})
test('path GET omits unsupported query and explicit refresh uses idempotency', async () => {
  transport.mockResolvedValue(reply(path)); expect(await getCurrentPath()).toEqual(path); await refreshPath('refresh-1')
  expect(transport.mock.calls[0][0]).toEqual({ method: 'get', url: 'recommendation/path', data: undefined, headers: undefined })
  expect(transport.mock.calls[1][0]).toEqual({ method: 'post', url: 'recommendation/refresh', data: {}, headers: { 'Idempotency-Key': 'refresh-1' } })
  expect(() => validatePath({ ...path, steps: [...path.steps, ...path.steps] })).toThrow()
})
test('generation is explicit and late results cannot cross accounts', async () => {
  const pending = deferred(); transport.mockReturnValueOnce(pending.promise)
  const ctx = context(); const vm = logic(AgentRun, { request }, ctx); expect(transport).not.toHaveBeenCalled()
  vm.generate(); ctx.store.getters.user.id = 2; pending.resolve(reply(run('succeeded')))
  await flushPromises(); await nextTick(); expect(vm.result).toBeNull(); expect(vm.busy).toBe(false)
})
test('invalidated runs can be abandoned before explicitly creating a fresh run', async () => {
  const vm = logic(AgentRun, { request }); vm.attempt = { key: 'old-key', runId: 'run-1' }
  transport.mockRejectedValueOnce({ response: { status: 503, data: { error: 'AGENT_DEPENDENCY_NOT_READY', data: { message: '资料已变化，请创建新运行' } } } })
  await vm.generate(); expect(vm.attempt.runId).toBe('run-1'); expect(vm.error).toContain('请创建新运行')
  vm.reset(); expect(vm.attempt).toEqual({}); transport.mockResolvedValueOnce(reply(run('succeeded', { run_id: 'run-2' })))
  await vm.generate(); expect(transport.mock.calls[1][0].method).toBe('post'); expect(transport.mock.calls[1][0].headers['Idempotency-Key']).not.toBe('old-key')
})
test('path explains stale links and links to actual display problem IDs', async () => {
  transport.mockResolvedValue(reply(path)); const ctx = context(); ctx.route.query = { path: 'old-path', revision: '3' }
  const vm = logic(LivePath, {}, ctx); await flushPromises(); expect(vm.outdated).toBe(true)
  expect(vm.problemLink(path.steps[0])).toEqual({ name: 'problem-details', params: { problemID: '1002' }, query: { from: 'learning-path', path: 'path-1', step: '1' } })
  vm.viewLatest(); expect(ctx.router.replace).toHaveBeenCalledWith({ query: {} })
})
test('missing paths prompt creation without a hidden POST', async () => {
  transport.mockRejectedValueOnce({ response: { status: 404, data: { error: 'LEARNING_PATH_NOT_FOUND', data: { message: '尚无活动路径' } } } })
  const vm = logic(LivePath, {}); await flushPromises(); expect(vm.empty).toBe(true); expect(transport).toHaveBeenCalledTimes(1)
})
test('guidance excludes contests and discards late conversations after logout', async () => {
  expect(logic(LiveGuidance, { problemId: '1002', contestId: '2' }).canRequest).toBe(false); expect(transport).not.toHaveBeenCalled()
  const pending = deferred(); transport.mockReturnValueOnce(pending.promise); const ctx = context(); const vm = logic(LiveGuidance, { problemId: '1002' }, ctx)
  ctx.store.getters.user.id = null; pending.resolve(reply({ problem_id: '1002', service_type: 'socratic_hint', conversation_id: 'c1', hint_level: 0, max_hint_level: 3, status: 'active', hint_available_time: new Date(0).toISOString() }))
  await flushPromises(); expect(vm.conversation).toBeNull()
})
test('analysis excludes other users and ongoing judging', () => {
  expect(logic(LiveAnalysis, { submission: { id: 's1', user_id: 2, result: 0 } }).state).toBe('forbidden')
  expect(logic(LiveAnalysis, { submission: { id: 's1', user_id: 1, result: 6 } }).state).toBe('pending'); expect(transport).not.toHaveBeenCalled()
})
test('production wrappers avoid prototype calls and feedback explains unavailable scope', async () => {
  logic(PrototypePath, {}); logic(PrototypeGuidance, { problemId: '1002' }); logic(PrototypeAnalysis, { submission: { id: 's1', user_id: 1, result: 0 } })
  const ctx = context(); const wrapper = mount(Feedback, { global: { mocks: { $store: ctx.store, $route: ctx.route }, stubs: { RouterLink: { template: '<a><slot /></a>' } } } })
  await flushPromises(); expect(wrapper.text()).toContain('近期学习复盘尚未开放'); expect(transport).not.toHaveBeenCalled(); wrapper.unmount()
})

test('live analysis supports backend MLE and PartialAC verdicts', () => {
  for (const result of [3, 8]) expect(logic(LiveAnalysis, { submission: { id: 's1', user_id: 1, result } }).state).toBe('idle')
})
test('initial login preserves deep links and known account switches clear them', async () => {
  transport.mockResolvedValue(reply(path)); const ctx = context(); ctx.store.getters.user.id = null
  ctx.route.query = { path: 'path-1', step: '1' }; const vm = logic(LivePath, {}, ctx)
  expect(transport).not.toHaveBeenCalled(); ctx.store.getters.user.id = 1; await flushPromises()
  expect(ctx.router.replace).not.toHaveBeenCalled(); expect(vm.path.path_id).toBe('path-1'); expect(vm.statusLabel('in_progress')).toBe('进行中')
  ctx.store.getters.user.id = 2; await flushPromises(); expect(ctx.router.replace).toHaveBeenCalledWith({ query: {} })
})

test('idempotency keys work on HTTP origins without randomUUID', () => {
  const randomUUID = vi.spyOn(crypto, 'randomUUID', 'get').mockReturnValue(undefined)
  expect(requestKey()).toMatch(/^web-[a-f0-9]{32}$/)
  randomUUID.mockRestore()
})
test('guidance enforces waiting and level limits while retaining real hint text', async () => {
  const conversation = { problem_id: '1002', service_type: 'socratic_hint', conversation_id: 'conversation-1', hint_level: 0, max_hint_level: 3, status: 'active', hint_available_time: new Date(Date.now() + 60000).toISOString() }
  transport.mockResolvedValue(reply(conversation))
  const vm = logic(LiveGuidance, { problemId: '1002' }); await flushPromises(); vm.thought = '我的理解是先遍历每个输入'
  expect(vm.canRequest).toBe(false); vm.now = Date.now() + 61000; expect(vm.canRequest).toBe(true)
  expect(vm.request).toEqual({ service_type: 'socratic_hint', problem_id: '1002', conversation_id: 'conversation-1', student_explanation: vm.thought })
  const hint = { hint_level: 1, focus: '循环边界', question: '最后一个元素是否被处理？', contains_full_solution: false }
  transport.mockResolvedValue(reply({ ...conversation, hint_level: 3 }))
  vm.acceptHint(hint); await flushPromises(); expect(vm.history[0].result).toEqual(hint); expect(vm.thought).toBe(''); expect(vm.exhausted).toBe(true)
})
