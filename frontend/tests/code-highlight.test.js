import { describe, expect, test } from 'vitest'
import { mount } from '@vue/test-utils'
import { h, withDirectives, resolveDirective } from 'vue'
import highlight from '../src/plugins/highlight'

describe('Vue 3 highlight directive', () => {
  test('real highlight engine handles initial empty code, repeated updates and code reset locally', async () => {
    const Component = {
      props: ['code'],
      render () { return withDirectives(h('pre', [h('code')]), [[resolveDirective('highlight'), this.code]]) }
    }
    const first = mount(Component, { props: { code: '' }, global: { plugins: [highlight] } })
    const other = mount(Component, { props: { code: 'print(1)' }, global: { plugins: [highlight] } })
    expect(first.text()).toBe('')
    expect(first.findAll('.hljs-ln')).toHaveLength(0)
    await first.setProps({ code: 'int main() {\n  return 0;\n}' })
    expect(first.findAll('.hljs-ln')).toHaveLength(1)
    expect(first.findAll('.hljs-ln tr')).toHaveLength(3)
    await first.setProps({ code: 'int main() { return 1; }' })
    expect(first.findAll('.hljs-ln')).toHaveLength(1)
    expect(first.text()).toContain('return 1')
    expect(other.text()).toBe('print(1)')
    await first.setProps({ code: 'int main() { return 1; }' })
    await first.vm.$forceUpdate()
    expect(first.findAll('.hljs-ln')).toHaveLength(1)
    await first.setProps({ code: '' })
    expect(first.text()).toBe('')
    expect(first.findAll('.hljs-ln')).toHaveLength(0)
    expect(other.text()).toBe('print(1)')
    first.unmount(); other.unmount()
  })
})
