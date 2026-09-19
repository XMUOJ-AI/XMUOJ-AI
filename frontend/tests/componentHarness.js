import { reactive } from 'vue'
import { mount } from '@vue/test-utils'
import { afterEach } from 'vitest'

const mounted = new Set()
afterEach(() => { for (const wrapper of mounted) wrapper.unmount(); mounted.clear() })

// These tests focus on reactive state and real Vue 3 lifecycle. UI rendering is
// covered separately by component and browser acceptance; no Vue 2 emulation is used.
export function mountLogic (options) {
  const { propsData = {}, ...component } = options
  const wrapper = mount({ ...component, render: () => null }, { props: propsData })
  mounted.add(wrapper)
  return new Proxy(wrapper.vm, {
    get (target, key) {
      if (key === '$unmount') return () => { wrapper.unmount(); mounted.delete(wrapper) }
      return Reflect.get(target, key)
    },
    set (target, key, value) {
      if (Object.prototype.hasOwnProperty.call(target.$props, key)) { wrapper.setProps({ [key]: value }); return true }
      return Reflect.set(target, key, value)
    }
  })
}

export function reactiveState (options) {
  return reactive({ ...options.data, $unmount () {} })
}
