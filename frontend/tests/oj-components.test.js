import { expect, test, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { h } from 'vue'
import LegacyButton from '../src/pages/oj/components/LegacyButton.vue'
import VerticalMenu from '../src/pages/oj/components/verticalMenu/verticalMenu.vue'
import VerticalMenuItem from '../src/pages/oj/components/verticalMenu/verticalMenu-item.vue'

test('student button blocks loading/disabled duplicate clicks and retains native button semantics', async () => {
  const onClick = vi.fn()
  const wrapper = mount(LegacyButton, { props: { type: 'primary', onClick }, slots: { default: '生成' }, global: { stubs: { Icon: true } } })
  expect(wrapper.attributes('type')).toBe('button')
  expect(wrapper.classes()).toContain('ivu-btn-primary')
  await wrapper.trigger('click')
  expect(onClick).toHaveBeenCalledTimes(1)
  await wrapper.setProps({ loading: true })
  await wrapper.trigger('click')
  expect(onClick).toHaveBeenCalledTimes(1)
  await wrapper.setProps({ loading: false, disabled: true })
  await wrapper.trigger('click')
  expect(onClick).toHaveBeenCalledTimes(1)
  wrapper.unmount()
})

test('nested vertical menu forwards one allowed route, and ignores a disabled item', async () => {
  const onClick = vi.fn()
  const allowed = { name: 'contest-problem-list', params: { contestID: '1' } }
  const wrapper = mount(VerticalMenu, {
    props: { 'onOn-click': onClick },
    slots: { default: () => [h('section', [h(VerticalMenuItem, { route: allowed }, () => '题目')]), h(VerticalMenuItem, { route: '/contest/2/rank', disabled: true }, () => '不可用')] },
    global: { stubs: { Card: { template: '<div><slot /></div>' } } }
  })
  await wrapper.findAll('li')[0].trigger('click')
  expect(onClick).toHaveBeenCalledTimes(1)
  expect(onClick).toHaveBeenCalledWith(allowed)
  await wrapper.findAll('li')[1].trigger('click')
  expect(onClick).toHaveBeenCalledTimes(1)
  wrapper.unmount()
})
