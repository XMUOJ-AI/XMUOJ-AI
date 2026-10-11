import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import PublicDetail from '../src/pages/oj/views/knowledge/KnowledgeDetail.vue'
import Explore from '../src/pages/oj/views/knowledge/KnowledgeExplore.vue'
import AdminDetail from '../src/pages/admin/views/knowledge/KnowledgeDetail.vue'
import Reviews from '../src/pages/admin/views/knowledge/KnowledgeReviews.vue'
import * as publicApi from '../src/pages/oj/views/knowledge/knowledgeApi'
import * as adminApi from '../src/pages/admin/views/knowledge/knowledgeAdminApi'

vi.mock('../src/pages/oj/views/knowledge/knowledgeApi', () => ({ loadKnowledgeDetail: vi.fn(), getKnowledgeCollection: vi.fn(), getKnowledge: vi.fn(), listKnowledge: vi.fn(), getKnowledgeGraph: vi.fn() }))
vi.mock('../src/pages/admin/views/knowledge/knowledgeAdminApi', () => ({
  getKnowledgePoint: vi.fn(), getKnowledgePointCollection: vi.fn(), updateKnowledgePoint: vi.fn(),
  deleteKnowledgePoint: vi.fn(), submitDependencyChange: vi.fn(), listKnowledgeReviews: vi.fn(),
  getKnowledgeReview: vi.fn(), reviewKnowledge: vi.fn()
}))

const wrappers = []
const empty = () => ({ items: [], total: 0, page: 1, page_size: 20, loading: false, error: '' })
const collections = () => ({ prerequisites: empty(), dependents: empty(), related_problems: empty() })
const point = () => ({ code: 'root', name: '原名称', description: '', category: 'basic', level: 1, aliases: [], metadata: {}, version: 4 })
const adminDetail = () => ({ knowledge_point: point(), capabilities: ['view', 'edit', 'request_dependency_change'], ...collections() })
const deferred = () => { let resolve; const promise = new Promise(done => { resolve = done }); return { promise, resolve } }

function create (component, render = false, query = {}) {
  const wrapper = mount(render ? component : { ...component, render: () => null }, {
    global: {
      mocks: {
        $route: { params: { code: 'root' }, query }, $router: { push: vi.fn() },
        $store: { getters: { isAuthenticated: true, isSuperAdmin: true } },
        $error: vi.fn(), $success: vi.fn(), $confirm: vi.fn().mockResolvedValue()
      },
      stubs: { NotFound: true, RouterLink: { template: '<a><slot /></a>' }, Button: true, Tag: true, Page: true }
    }
  })
  wrappers.push(wrapper)
  return wrapper
}

beforeEach(() => {
  for (const fn of [...Object.values(publicApi), ...Object.values(adminApi)]) fn.mockReset()
  publicApi.loadKnowledgeDetail.mockResolvedValue({ point: point(), collections: collections() })
  adminApi.getKnowledgePoint.mockImplementation(async () => adminDetail())
  adminApi.listKnowledgeReviews.mockResolvedValue({ items: [], total: 0 })
})
afterEach(() => { wrappers.splice(0).forEach(wrapper => wrapper.unmount()) })

describe('knowledge pages against local backend', () => {
  test('graph node summary omits large collections outside the current list page', async () => {
    publicApi.getKnowledge.mockResolvedValue(point())
    const state = { summaryRequest: 0, alive: true, selected: { code: 'root' }, summaryLoading: false, summaryError: '' }
    await Explore.methods.loadSummary.call(state, 'root')
    expect(publicApi.getKnowledge).toHaveBeenCalledWith('root', { include_collections: false })
    expect(state.selected.name).toBe('原名称')
    expect(state.summaryLoading).toBe(false)
    expect(state.summaryError).toBe('')
  })

  test('renders complete totals and independently pages a public collection beyond 100 items', async () => {
    const initial = collections()
    initial.related_problems = { ...empty(), total: 121, items: [{ display_id: 'P001', title: '第一页' }] }
    publicApi.loadKnowledgeDetail.mockResolvedValue({ point: point(), collections: initial })
    publicApi.getKnowledgeCollection.mockResolvedValue({ items: [{ display_id: 'P121', title: '最后一页' }], total: 121, page: 7, page_size: 20 })
    const wrapper = create(PublicDetail, true)
    await flushPromises()
    expect(wrapper.text()).toContain('关联题目（121）')
    expect(wrapper.findComponent({ name: 'Page' }).exists()).toBe(true)
    await wrapper.vm.loadCollection('related_problems', 7)
    expect(publicApi.getKnowledgeCollection).toHaveBeenCalledWith('root', 'related_problems', 7)
    expect(wrapper.text()).toContain('P121')
    expect(wrapper.text()).not.toContain('P001')
    expect(wrapper.vm.collections.prerequisites.page).toBe(1)
  })

  test('a late public page response cannot replace a newly selected knowledge point', async () => {
    const waiting = deferred()
    publicApi.getKnowledgeCollection.mockReturnValue(waiting.promise)
    const wrapper = create(PublicDetail)
    await flushPromises()
    const loading = wrapper.vm.loadCollection('dependents', 2)
    publicApi.loadKnowledgeDetail.mockResolvedValue({ point: { ...point(), code: 'next' }, collections: collections() })
    await wrapper.vm.load()
    waiting.resolve({ items: [{ code: 'stale' }], page: 2, page_size: 20, total: 30 })
    await loading
    expect(wrapper.vm.point.code).toBe('next')
    expect(wrapper.vm.collections.dependents.items).toEqual([])
  })

  test('admin dependencies after row 100 retain the ID and version required for changes', async () => {
    const dependency = { code: 'parent', dependency_id: 101, version: 3, relation_type: 'required', weight: 0.5 }
    adminApi.getKnowledgePointCollection.mockResolvedValue({ items: [dependency], total: 101, page: 2, page_size: 100 })
    adminApi.submitDependencyChange.mockResolvedValue({ request_id: 'change' })
    const wrapper = create(AdminDetail)
    await flushPromises()
    await wrapper.vm.loadCollection('prerequisites', 2)
    expect(wrapper.vm.collections.prerequisites.page).toBe(2)
    wrapper.vm.openDependencyChange(wrapper.vm.detail.prerequisites.items[0], 'root')
    wrapper.vm.dependency.reason = '修订依赖'
    await wrapper.vm.submitDependency()
    expect(adminApi.submitDependencyChange).toHaveBeenCalledWith({
      operation: 'update', target_dependency_id: 101, base_version: 3, prerequisite_code: 'parent', dependent_code: 'root',
      relation_type: 'required', weight: 0.5, reason: '修订依赖'
    })
  })

  test('edit conflict refreshes the version while preserving the open form and user input', async () => {
    adminApi.updateKnowledgePoint.mockRejectedValue({ code: 'KNOWLEDGE_VERSION_CONFLICT', status: 409 })
    const wrapper = create(AdminDetail, false, { edit: '1' })
    await flushPromises()
    wrapper.vm.editing.name = '未保存输入'
    adminApi.getKnowledgePoint.mockResolvedValue({ ...adminDetail(), knowledge_point: { ...point(), version: 5 } })
    await wrapper.vm.saveEdit()
    expect(adminApi.updateKnowledgePoint).toHaveBeenCalledWith('root', expect.objectContaining({ version: 4, name: '未保存输入', description: '' }))
    expect(wrapper.vm.editVisible).toBe(true)
    expect(wrapper.vm.editing.name).toBe('未保存输入')
    expect(wrapper.vm.point.version).toBe(5)
  })

  test('review defaults match pending and permissions block self-review submission', async () => {
    const wrapper = create(Reviews, false, { status: '' })
    await flushPromises()
    expect(wrapper.vm.draft.status).toBe('pending')
    expect(adminApi.listKnowledgeReviews).toHaveBeenCalledWith(expect.objectContaining({ status: 'pending' }))
    wrapper.vm.currentRow = { object_type: 'dependency_change', object_key: 'self' }
    wrapper.vm.detail = { object_type: 'dependency_change', request: { status: 'pending', updated_time: 'original' }, capabilities: [] }
    await wrapper.vm.act('approve', {})
    expect(adminApi.reviewKnowledge).not.toHaveBeenCalled()
    wrapper.vm.detail.capabilities = ['reject']
    await wrapper.vm.act('approve', {})
    expect(adminApi.reviewKnowledge).not.toHaveBeenCalled()
  })

  test('late review details cannot authorize an action on another row', async () => {
    const first = deferred()
    adminApi.getKnowledgeReview.mockReturnValueOnce(first.promise).mockResolvedValueOnce({
      object_type: 'dependency_change', request: { status: 'pending', updated_time: 'second-version' }, capabilities: []
    })
    const wrapper = create(Reviews)
    await flushPromises()
    const loading = wrapper.vm.openDetail({ object_type: 'dependency_change', object_key: 'first' })
    await wrapper.vm.openDetail({ object_type: 'dependency_change', object_key: 'second' })
    first.resolve({ object_type: 'dependency_change', request: { status: 'pending', updated_time: 'first-version' }, capabilities: ['approve'] })
    await loading
    expect(wrapper.vm.detail.request.updated_time).toBe('second-version')
    expect(wrapper.vm.canReview('approve')).toBe(false)
    await wrapper.vm.act('approve', {})
    expect(adminApi.reviewKnowledge).not.toHaveBeenCalled()
  })

  test('confirming one review cannot approve another selection', async () => {
    const confirmation = deferred()
    const wrapper = create(Reviews)
    await flushPromises()
    wrapper.vm.$confirm.mockReturnValue(confirmation.promise)
    wrapper.vm.currentRow = { object_type: 'dependency_change', object_key: 'first', target_summary: { label: 'First' } }
    const approving = wrapper.vm.approve()
    wrapper.vm.currentRow = { object_type: 'dependency_change', object_key: 'second', target_summary: { label: 'Second' } }
    wrapper.vm.detail = { object_type: 'dependency_change', request: { status: 'pending', updated_time: 'second-version' }, capabilities: ['approve'] }
    confirmation.resolve()
    await approving
    expect(adminApi.reviewKnowledge).not.toHaveBeenCalled()
  })
})
