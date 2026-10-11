import { expect, test, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { createStore } from 'vuex'
import Governance from '../src/pages/admin/views/problem/ProblemTagGovernance.vue'

const fixture = vi.hoisted(() => ({ row: { id: 1, name: 'BFS', normalized_name: 'bfs', is_active: true, aliases: [], problem_count: 1, rank: 0, description: '' }, updates: [] }))
vi.mock('@admin/api', () => ({ default: {
  getProblemTagList: () => Promise.resolve({ data: { data: [{ ...fixture.row }] } }),
  getProblemTagAudit: () => Promise.resolve({ data: { data: { summary: { total_tags: 1, active_tags: 1, duplicate_groups: 0, zero_problem_tags: 0 }, duplicates: [], zero_problem_tags: [], low_frequency_tags: [], alias_conflicts: [] } } }),
  updateProblemTag: payload => { fixture.updates.push(payload); Object.assign(fixture.row, payload); return Promise.resolve({ data: { data: fixture.row } }) }
} }))

test('real Element Plus switch in a governance table row renders true and sends false on toggle', async () => {
  fixture.row.is_active = true
  fixture.updates.length = 0
  const store = createStore({ getters: { isSuperAdmin: () => true } })
  const wrapper = mount(Governance, { attachTo: document.body, global: {
    plugins: [store, ElementPlus],
    mocks: { $t: key => key, $success: vi.fn() },
    stubs: { Panel: { template: '<section><slot name="header" /><slot /></section>' }, Save: true, Cancel: true }
  } })
  try {
    await flushPromises()
    const rowSwitch = wrapper.get('tbody .el-switch [role="switch"]')
    expect(rowSwitch.attributes('aria-checked')).toBe('true')
    await rowSwitch.trigger('click')
    await flushPromises()
    expect(fixture.updates).toHaveLength(1)
    expect(fixture.updates[0]).toMatchObject({ id: 1, is_active: false })
    expect(wrapper.get('tbody .el-switch [role="switch"]').attributes('aria-checked')).toBe('false')
  } finally { wrapper.unmount() }
})
