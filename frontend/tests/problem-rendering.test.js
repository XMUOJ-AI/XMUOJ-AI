import { expect, test, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { h, ref } from 'vue'
import { createStore } from 'vuex'
import Problem from '../src/pages/oj/views/problem/Problem.vue'
import katex from '../src/plugins/katex'

const pending = vi.hoisted(() => [])
vi.mock('@oj/api', () => ({ default: {
  getProblem: vi.fn(() => new Promise(resolve => pending.push(resolve))),
  submissionExists: vi.fn(() => Promise.resolve({ data: { data: false } }))
} }))
vi.mock('../src/store', () => ({ types: { CHANGE_CONTEST_ITEM_VISIBLE: 'visibility' } }))
vi.mock('../src/pages/oj/components/CodeMirror.vue', () => ({ default: { render: () => null } }))
vi.mock('../src/pages/oj/views/problem/ProblemGuidance.vue', () => ({ default: { render: () => null } }))
vi.mock('@/i18n', () => ({ default: { t: key => key } }))

const Slot = { inheritAttrs: false, setup (_, { slots }) { return () => h('div', slots.default && slots.default()) } }
const fixture = (id, samples) => ({
  id, _id: String(1000 + id), title: 'Mock ' + id,
  description: '<span>计算 $a+b$。</span>', input_description: '<span>输入 $a$ 和 $b$。</span>', output_description: '<span>输出 $a+b$。</span>',
  hint: '<span>考虑 $0$。</span>', source: '练习 $x$', samples,
  created_by: { username: 'teacher' }, template: {}, languages: ['C++'], tags: ['模拟'],
  io_mode: { io_mode: 'File IO', input: 'input.txt', output: 'output.txt' }, can_download_test_case: true
})

test('real Problem math leaves preserve Vue anchors during load, sample changes and route changes', async () => {
  pending.length = 0
  const route = ref({ name: 'problem-details', params: { problemID: '1001' }, query: {} })
  const store = createStore({
    state: { contest: { contest: {} } },
    getters: { problemSubmitDisabled: () => false, contestRuleType: () => 'ACM', OIContestRealTimePermission: () => true, contestStatus: () => '0', canViewContestRank: () => false, isAuthenticated: () => true },
    mutations: { visibility () {} }, actions: { changeDomTitle () {} }
  })
  const wrapper = mount(Problem, {
    global: {
      plugins: [store, katex, { install (app) { Object.defineProperty(app.config.globalProperties, '$route', { get: () => route.value }) } }],
      mocks: { $t: key => key, $i18n: { t: key => key }, $Loading: { start () {}, finish () {}, error () {} } },
      directives: { clipboard: {} },
      stubs: Object.fromEntries(['Panel', 'Card', 'Row', 'Col', 'Button', 'Icon', 'Tag', 'Tooltip', 'Poptip', 'Input', 'VerticalMenu', 'VerticalMenuItem', 'ECharts', 'Modal', 'RouterLink', 'Alert'].map(name => [name, Slot]))
    }
  })
  expect(pending).toHaveLength(1)
  pending.shift()({ data: { data: fixture(1, [{ input: '1 2', output: '3' }, { input: '2 3', output: '5' }]) } })
  await flushPromises()
  expect(wrapper.findAll('.sample')).toHaveLength(2)
  expect(wrapper.findAll('#problem-content .katex').length).toBeGreaterThanOrEqual(6)
  expect(wrapper.get('#problem-content').text()).toContain('input.txt')

  // Remove and restore adjacent v-if/v-for fragments after KaTeX has changed leaf DOM.
  await wrapper.setData({ problem: { ...wrapper.vm.problem, samples: [], hint: '', source: '', can_download_test_case: false, io_mode: { io_mode: 'Standard IO' } } })
  expect(wrapper.findAll('.sample')).toHaveLength(0)
  expect(wrapper.get('#problem-content').text()).not.toContain('input.txt')
  route.value = { name: 'problem-details', params: { problemID: '1002' }, query: {} }
  await flushPromises()
  expect(pending).toHaveLength(1)
  const next = fixture(2, [{ input: '8 9', output: '17' }])
  next.source = '<img src=x onerror=alert(1)> literal source'
  pending.shift()({ data: { data: next } })
  await flushPromises()
  expect(wrapper.findAll('.sample')).toHaveLength(1)
  expect(wrapper.get('.sample').text()).toContain('8 9')
  expect(wrapper.get('#problem-content').text()).not.toContain('2 3')
  expect(wrapper.get('#problem-content').text()).toContain('<img src=x onerror=alert(1)> literal source')
  expect(wrapper.find('#problem-content img').exists()).toBe(false)
  await wrapper.setData({ problem: fixture(3, [{ input: '3', output: '6' }, { input: '4', output: '8' }, { input: '5', output: '10' }]) })
  expect(wrapper.findAll('.sample')).toHaveLength(3)
  expect(wrapper.get('#problem-content').text()).not.toContain('literal source')
  expect(wrapper.findAll('#problem-content .katex').length).toBeGreaterThanOrEqual(6)
  wrapper.unmount()
})
