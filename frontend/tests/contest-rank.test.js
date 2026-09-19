import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { h, ref } from 'vue'
import { createStore } from 'vuex'
import OIRank from '../src/pages/oj/views/contest/children/OIContestRank.vue'
import ContestRank from '../src/pages/oj/views/contest/children/ContestRank.vue'

const requests = vi.hoisted(() => [])
vi.mock('@oj/api', () => ({ default: { getContestRank: params => new Promise((resolve, reject) => requests.push({ params, resolve, reject })) } }))
vi.mock('@/store', () => ({ types: { CHANGE_CONTEST_ITEM_VISIBLE: 'visible', CHANGE_RANK_FORCE_UPDATE: 'force', CHANGE_CONTEST_RANK_LIMIT: 'limit' } }))
vi.mock('@admin/components/ScreenFull.vue', () => ({ default: { render: () => null } }))
vi.mock('../src/pages/oj/views/contest/children/ACMContestRank.vue', () => ({ default: { render: () => null } }))
const wrappers = []
const Slot = { inheritAttrs: false, setup (_, { slots }) { return () => h('div', slots.default && slots.default()) } }
const Chart = { props: ['options'], methods: { showLoading: vi.fn(), hideLoading: vi.fn(), resize: vi.fn() }, render: () => h('div', { class: 'rank-chart' }) }
const Table = { methods: { handleResize: vi.fn() }, render: () => h('div', { class: 'rank-table' }) }
const answer = (name = 'current', score = 100) => ({ data: { data: { total: 1, results: [{ user: { username: name }, total_score: score, submission_info: { 1: score } }] } } })

function setup (component = OIRank, allowed = false) {
  const problems = []
  const route = ref({ params: { contestID: '1' }, query: {} })
  const store = createStore({
    state: { allowed, user: { id: 1 }, contest: { contest: { id: 1, title: 'OI fixture', rule_type: 'OI', status: '0' }, contestProblems: [], rankLimit: 30, forceUpdate: false, itemVisible: { chart: true, menu: true, realName: false } } },
    getters: { canViewContestRank: state => state.allowed, user: state => state.user, isContestAdmin: () => true, contestRuleType: state => state.contest.contest.rule_type },
    mutations: {
      allowed (state, value) { state.allowed = value },
      user (state, id) { state.user = { id } },
      contest (state, id) { state.contest.contest = { ...state.contest.contest, id }; state.contest.contestProblems = [] },
      visible (state, value) { Object.assign(state.contest.itemVisible, value) }
    },
    actions: { getContestProblems: () => new Promise(resolve => problems.push(resolve)) }
  })
  const wrapper = mount(component, { global: {
    plugins: [store, { install (app) { Object.defineProperty(app.config.globalProperties, '$route', { get: () => route.value }) } }],
    mocks: { $t: key => key, $i18n: { t: key => key }, $router: { push: vi.fn() } },
    stubs: { Panel: Slot, Poptip: Slot, Icon: Slot, ISwitch: Slot, Button: Slot, Pagination: Slot, ECharts: Chart, Table }
  } })
  wrappers.push(wrapper)
  return { wrapper, store, route, problems }
}
beforeEach(() => { requests.length = 0; vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] }) })
afterEach(() => { for (const wrapper of wrappers.splice(0)) wrapper.unmount(); vi.useRealTimers() })

test('late OI permission mounts chart refs before requesting and prevents duplicate problem columns', async () => {
  const { wrapper, store, problems } = setup()
  expect(requests).toHaveLength(0)
  expect(problems).toHaveLength(0)
  expect(wrapper.find('.rank-chart').exists()).toBe(false)
  store.commit('allowed', true)
  await flushPromises()
  expect(wrapper.find('.rank-chart').exists()).toBe(true)
  expect(requests).toHaveLength(1)
  requests[0].resolve(answer())
  problems[0]({ data: { data: [{ id: 1, _id: '1001' }] } })
  await flushPromises()
  expect(wrapper.vm.total).toBe(1)
  expect(wrapper.vm.dataRank[0].user.username).toBe('current')
  const columns = wrapper.vm.columns.length
  store.commit('allowed', false); await flushPromises()
  store.commit('allowed', true); await flushPromises()
  expect(wrapper.vm.columns).toHaveLength(columns)
  expect(problems).toHaveLength(1)
  requests[1].resolve(answer('refreshed')); await flushPromises()
  expect(wrapper.vm.dataRank[0].user.username).toBe('refreshed')
})

test('permission loss clears visible data, rejects late replies and stops polling', async () => {
  const { wrapper, store } = setup(OIRank, true)
  requests[0].resolve(answer('initial')); await flushPromises()
  wrapper.vm.getContestRankData()
  wrapper.vm.handleAutoRefresh(true)
  const pending = requests[1]
  store.commit('allowed', false); await flushPromises()
  expect(wrapper.find('.rank-chart').exists()).toBe(false)
  expect(wrapper.vm.dataRank).toEqual([])
  expect(wrapper.vm.total).toBe(0)
  pending.resolve(answer('must not appear')); await flushPromises()
  expect(wrapper.vm.dataRank).toEqual([])
  vi.advanceTimersByTime(60000)
  expect(requests).toHaveLength(2)
})

test('late rank and column responses cannot update an unmounted contest, and new contest starts fresh', async () => {
  const { wrapper, store, route, problems } = setup(ContestRank, true)
  const oldPage = wrapper.findComponent(OIRank).vm
  const oldColumns = oldPage.columns.length
  oldPage.handleAutoRefresh(true)
  store.commit('contest', 2)
  route.value = { params: { contestID: '2' }, query: {} }
  await flushPromises()
  const page = wrapper.findComponent(OIRank).vm
  expect(page === oldPage).toBe(false)
  expect(requests[1].params.contest_id).toBe('2')
  requests[0].resolve(answer('old contest'))
  problems[0]({ data: { data: [{ id: 7, _id: 'old-column' }] } })
  await flushPromises()
  expect(oldPage.dataRank).toEqual([])
  expect(oldPage.columns).toHaveLength(oldColumns)
  expect(page.dataRank).toEqual([])
  problems[1]({ data: { data: [{ id: 2, _id: '2001' }] } })
  requests[1].resolve(answer('new contest')); await flushPromises()
  expect(page.dataRank[0].user.username).toBe('new contest')
  expect(page.columns.some(column => column.key === 7)).toBe(false)
  vi.advanceTimersByTime(60000)
  expect(requests).toHaveLength(2)
  page.getContestRankData()
  const lastRows = JSON.stringify(page.dataRank)
  wrapper.unmount()
  requests[2].resolve(answer('after unmount')); await flushPromises()
  expect(JSON.stringify(page.dataRank)).toBe(lastRows)
})

test('rank request identity prevents old-account response from updating the page', async () => {
  const { wrapper, store } = setup(OIRank, true)
  store.commit('user', 2)
  requests[0].resolve(answer('old account')); await flushPromises()
  expect(wrapper.vm.dataRank).toEqual([])
  wrapper.vm.getContestRankData()
  requests[1].resolve(answer('current account')); await flushPromises()
  expect(wrapper.vm.dataRank[0].user.username).toBe('current account')
})
