import { describe, expect, test, vi } from 'vitest'
import { nextTick } from 'vue'
import { mount } from '@vue/test-utils'
import KnowledgeGraph from '../src/pages/oj/views/knowledge/KnowledgeGraph.vue'
import { layoutKnowledgeGraph } from '../src/pages/oj/views/knowledge/knowledgeGraphLayout'

const nodes = ['root', 'parent', 'grandparent', 'child', 'grandchild', 'sibling'].map(code => ({ code, name: code, level: 1 }))
const edges = [
  ['grandparent', 'parent'], ['parent', 'root'], ['root', 'child'], ['child', 'grandchild'], ['parent', 'sibling']
].map(([from, to]) => ({ from, to, relation_type: 'required', weight: 1 }))
const graph = { nodes, edges, truncated: false }

describe('centered local knowledge graph', () => {
  test('keeps the selected root centered and assigns directed layers to each side', () => {
    const layout = layoutKnowledgeGraph(graph, 'root', true)
    const byCode = Object.fromEntries(layout.nodes.map(node => [node.code, node]))
    expect(byCode.root.x + 78).toBe(layout.width / 2)
    expect(byCode.root.y + 26).toBe(layout.height / 2)
    expect(byCode.grandparent.x).toBeLessThan(byCode.parent.x)
    expect(byCode.parent.x).toBeLessThan(byCode.root.x)
    expect(byCode.root.x).toBeLessThan(byCode.child.x)
    expect(byCode.child.x).toBeLessThan(byCode.grandchild.x)
    expect(byCode.sibling).toBeUndefined()
    expect(layout.edges.every(edge => edge.from !== 'sibling' && edge.to !== 'sibling')).toBe(true)
  })

  test('shows only returned layers and emits a selection instead of navigating', async () => {
    const oneLayer = { nodes: nodes.filter(node => ['parent', 'root', 'child'].includes(node.code)), edges: edges.filter(edge => ['parent', 'root', 'child'].includes(edge.from) && ['parent', 'root', 'child'].includes(edge.to)) }
    const wrapper = mount(KnowledgeGraph, { props: { graph: oneLayer, rootCode: 'root', directional: true } })
    expect(wrapper.findAll('.graph-node')).toHaveLength(3)
    await wrapper.findAll('.graph-node-main').find(node => node.attributes('aria-label').includes('child')).trigger('click')
    expect(wrapper.emitted('select-node')[0]).toEqual(['child'])
    wrapper.unmount()
  })

  test('opens a node detail from its corner link without selecting the node', async () => {
    const push = vi.fn()
    const wrapper = mount(KnowledgeGraph, { props: { graph, rootCode: 'root', directional: true }, global: { mocks: { $router: { push } } } })
    const link = wrapper.findAll('.graph-detail-link').find(item => item.attributes('aria-label').includes('child'))
    await link.trigger('click')
    expect(push).toHaveBeenCalledWith({ name: 'knowledge-detail', params: { code: 'child' } })
    expect(wrapper.emitted('select-node')).toBeUndefined()
    wrapper.unmount()
  })

  test('uses natural size by default and scales only when fit is requested', async () => {
    const wrapper = mount(KnowledgeGraph, { props: { graph, rootCode: 'root', directional: true } })
    await nextTick()
    const width = layoutKnowledgeGraph(graph, 'root', true).width
    expect(wrapper.vm.scale).toBe(1)
    expect(Number(wrapper.find('svg').attributes('width'))).toBe(width)
    Object.defineProperty(wrapper.vm.$refs.shell, 'clientWidth', { configurable: true, value: 420 })
    Object.defineProperty(wrapper.vm.$refs.shell, 'clientHeight', { configurable: true, value: 260 })
    wrapper.vm.fit()
    await nextTick()
    expect(Number(wrapper.find('svg').attributes('width'))).toBeLessThan(width)
    wrapper.unmount()
  })

  test('zooms in and out within bounds', async () => {
    const wrapper = mount(KnowledgeGraph, { props: { graph, rootCode: 'root', directional: true } })
    wrapper.vm.zoom(0.25)
    await nextTick()
    expect(wrapper.vm.scale).toBe(1.25)
    expect(Number(wrapper.find('svg').attributes('width'))).toBeGreaterThan(wrapper.vm.layout.width)
    wrapper.vm.zoom(-0.25)
    expect(wrapper.vm.scale).toBe(1)
    wrapper.vm.zoom(-10)
    expect(wrapper.vm.scale).toBe(0.25)
    wrapper.vm.zoom(10)
    expect(wrapper.vm.scale).toBe(2.5)
    wrapper.unmount()
  })

  test('drags the canvas without selecting a node, while a normal click still selects it', async () => {
    const wrapper = mount(KnowledgeGraph, { props: { graph, rootCode: 'root', directional: true } })
    const shell = wrapper.find('.graph-shell')
    const node = wrapper.find('.graph-node-main')
    const pointer = (type, options) => {
      const event = new Event(type, { bubbles: true, cancelable: true })
      Object.entries(options).forEach(([key, value]) => Object.defineProperty(event, key, { value }))
      node.element.dispatchEvent(event)
    }
    shell.element.scrollLeft = 200
    shell.element.scrollTop = 100
    expect(shell.classes()).not.toContain('dragging')
    pointer('pointerdown', { button: 0, pointerId: 1, clientX: 100, clientY: 100 })
    await nextTick()
    expect(shell.classes()).toContain('dragging')
    pointer('pointermove', { pointerId: 1, clientX: 70, clientY: 80 })
    expect(shell.element.scrollLeft).toBe(230)
    expect(shell.element.scrollTop).toBe(120)
    pointer('pointerup', { pointerId: 1 })
    await nextTick()
    expect(shell.classes()).not.toContain('dragging')
    await node.trigger('click')
    expect(wrapper.emitted('select-node')).toBeUndefined()
    pointer('pointerdown', { button: 0, pointerId: 2, clientX: 100, clientY: 100 })
    pointer('pointerup', { pointerId: 2 })
    await node.trigger('click')
    expect(wrapper.emitted('select-node')).toHaveLength(1)
    wrapper.unmount()
  })
})
