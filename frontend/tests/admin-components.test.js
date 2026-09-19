import { beforeEach, describe, expect, test, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { h } from 'vue'
import Save from '../src/pages/admin/components/btn/Save.vue'
import Cancel from '../src/pages/admin/components/btn/Cancel.vue'
import IconBtn from '../src/pages/admin/components/btn/IconBtn.vue'
import CodeMirror from '../src/pages/admin/components/CodeMirror.vue'
import StudentCodeMirror from '../src/pages/oj/components/CodeMirrorInput.vue'
import Simditor from '../src/pages/admin/components/Simditor.vue'
import Problem from '../src/pages/admin/views/problem/Problem.vue'

const editors = vi.hoisted(() => [])
vi.mock('codemirror', () => ({ default: { fromTextArea: () => {
  const events = {}; let value = ''
  const editor = {
    on: vi.fn((name, fn) => { events[name] = fn }),
    off: vi.fn(name => { delete events[name] }),
    getValue: () => value,
    setValue: vi.fn(next => { value = next; if (events.change) events.change(editor) }),
    getCursor: () => ({ line: 0, ch: 1 }), getScrollInfo: () => ({ left: 3, top: 4 }),
    setCursor: vi.fn(), scrollTo: vi.fn(), setOption: vi.fn(), refresh: vi.fn(), toTextArea: vi.fn()
  }
  editors.push(editor); return editor
} } }))
vi.mock('codemirror/mode/clike/clike.js', () => ({}))
vi.mock('codemirror/mode/python/python.js', () => ({}))
vi.mock('tar-simditor-markdown', () => ({}))
vi.mock('../src/pages/admin/components/simditor-file-upload', () => ({}))
vi.mock('tar-simditor', () => ({ default: class {
  constructor () {
    const events = {}; let value = ''
    this.on = vi.fn((name, fn) => { events[name] = fn })
    this.off = vi.fn(name => { delete events[name] })
    this.getValue = () => value
    this.setValue = vi.fn(next => { value = next; if (events.valuechanged) events.valuechanged() })
    this.destroy = vi.fn()
    editors.push(this)
  }
} }))
vi.mock('@admin/api', () => ({ default: {} }))
const Button = { emits: ['click'], setup (_, { emit, slots }) { return () => h('button', { onClick: event => emit('click', event) }, slots.default && slots.default()) } }
const Tooltip = { inheritAttrs: false, setup (_, { slots }) { return () => slots.default && slots.default() } }
const global = { mocks: { $t: key => key }, stubs: { 'el-button': Button, 'el-tooltip': Tooltip } }
beforeEach(() => { editors.length = 0 })

describe('admin component contracts', () => {
  for (const component of [Save, Cancel, IconBtn]) test(component.name + ' delivers one click to the parent', async () => {
    const onClick = vi.fn()
    const wrapper = mount(component, { props: { name: 'Edit', icon: 'edit', onClick }, global })
    await wrapper.get('button').trigger('click')
    expect(onClick).toHaveBeenCalledTimes(1)
    expect(wrapper.emitted('click')).toHaveLength(1)
    wrapper.unmount()
  })
  test('CodeMirror external model update does not echo; user edits emit once and release on unmount', async () => {
    const wrapper = mount(CodeMirror, { props: { modelValue: 'old', mode: 'text/x-csrc' } })
    const editor = editors[0]
    expect(editor.getValue()).toBe('old')
    expect(wrapper.emitted('update:modelValue')).toBeUndefined()
    await wrapper.setProps({ modelValue: 'server updated' })
    expect(editor.getValue()).toBe('server updated')
    expect(wrapper.emitted('update:modelValue')).toBeUndefined()
    expect(editor.setCursor).toHaveBeenCalledWith({ line: 0, ch: 1 })
    editor.setValue('typed by user')
    expect(wrapper.emitted('update:modelValue')).toEqual([['typed by user']])
    await wrapper.setProps({ modelValue: 'typed by user', mode: 'text/x-python' })
    expect(wrapper.emitted('update:modelValue')).toHaveLength(1)
    expect(editor.setOption).toHaveBeenCalledWith('mode', 'text/x-python')
    wrapper.unmount()
    expect(editor.off).toHaveBeenCalledWith('change', expect.any(Function))
    expect(editor.toTextArea).toHaveBeenCalledTimes(1)
  })
  test('Simditor external HTML update does not echo and destroys editor/listeners', async () => {
    const wrapper = mount(Simditor, { props: { modelValue: '<p>old</p>' }, global })
    const editor = editors[0]
    await wrapper.setProps({ modelValue: '<p>server</p>' })
    expect(editor.getValue()).toBe('<p>server</p>')
    expect(wrapper.emitted('update:modelValue')).toBeUndefined()
    editor.setValue('<p>typed</p>')
    expect(wrapper.emitted('update:modelValue')).toEqual([['<p>typed</p>']])
    wrapper.unmount()
    expect(editor.off).toHaveBeenCalledWith('valuechanged', expect.any(Function))
    expect(editor.off).toHaveBeenCalledWith('decorate', expect.any(Function))
    expect(editor.destroy).toHaveBeenCalledTimes(1)
  })
  test('student editor preserves cursor/scroll on prop sync without emitting user edits', async () => {
    const wrapper = mount(StudentCodeMirror, { props: { value: 'initial' } })
    const editor = editors[0]
    await wrapper.setProps({ value: 'server restored code' })
    expect(editor.getValue()).toBe('server restored code')
    expect(editor.setCursor).toHaveBeenCalledWith({ line: 0, ch: 1 })
    expect(editor.scrollTo).toHaveBeenCalledWith(3, 4)
    expect(wrapper.emitted('change')).toBeUndefined()
    editor.setValue('user typed code')
    expect(wrapper.emitted('change')).toEqual([['user typed code']])
    await wrapper.setProps({ value: 'user typed code' })
    expect(wrapper.emitted('change')).toHaveLength(1)
    wrapper.unmount()
    expect(editor.toTextArea).toHaveBeenCalledTimes(1)
  })
  test('cancelling SPJ mode change preserves mode and uploaded cases', async () => {
    const state = { testCaseUploaded: true, problem: { spj: false }, $confirm: vi.fn(() => Promise.reject('cancel')), resetTestCase: vi.fn() }
    Problem.methods.switchSpj.call(state)
    await flushPromises()
    expect(state.problem.spj).toBe(false)
    expect(state.resetTestCase).not.toHaveBeenCalled()
    state.$confirm.mockResolvedValue(undefined)
    Problem.methods.switchSpj.call(state)
    await flushPromises()
    expect(state.problem.spj).toBe(true)
    expect(state.resetTestCase).toHaveBeenCalledTimes(1)
  })
})
