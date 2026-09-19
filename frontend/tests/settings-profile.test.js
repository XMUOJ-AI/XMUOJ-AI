import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { h } from 'vue'
import { createStore } from 'vuex'
import ProfileSetting from '../src/pages/oj/views/setting/children/ProfileSetting.vue'
import AccountSetting from '../src/pages/oj/views/setting/children/AccountSetting.vue'
import SecuritySetting from '../src/pages/oj/views/setting/children/SecuritySetting.vue'

const requests = vi.hoisted(() => ({ updateProfile: [], changePassword: [], changeEmail: [], getSessions: [], twoFactorAuth: [] }))
vi.mock('@oj/api', () => ({ default: Object.fromEntries(Object.keys(requests).map(name => [name, (...args) => new Promise((resolve, reject) => requests[name].push({ args, resolve, reject }))])) }))
vi.mock('@/store', () => ({ types: { CHANGE_PROFILE: 'profile' } }))
vi.mock('@/i18n', () => ({ languages: [{ value: 'zh-CN', label: '简体中文' }], default: { t: key => key } }))
vi.mock('vue-cropper', () => ({ VueCropper: { render: () => null } }))
const wrappers = []
const Slot = { inheritAttrs: false, setup (_, { slots }) { return () => h('div', slots.default && slots.default()) } }
const Form = { ...Slot, methods: { validate (callback) { callback(true) }, resetFields () {}, validateField () {} } }
const FormItem = { props: ['label'], setup (props, { slots }) { return () => h('label', { 'data-label': props.label }, slots.default && slots.default()) } }
const Input = { props: ['modelValue', 'disabled'], emits: ['update:modelValue'], setup (props, { emit }) { return () => h('input', { value: props.modelValue, disabled: props.disabled, onInput: event => emit('update:modelValue', event.target.value) }) } }
const profile = (id = 1, fields = {}) => ({ user: { id, email: 'user' + id + '@example.test', two_factor_auth: false }, real_name: '同学' + id, school: '厦门大学', major: '软件工程', language: 'zh-CN', mood: '原始签名', ...fields })
function setup (component, initial = {}) {
  const store = createStore({ state: { user: { profile: initial } }, getters: { user: state => state.user.profile.user || {} }, mutations: { profile (state, payload) { state.user.profile = payload.profile } }, actions: { getProfile () {} } })
  const push = vi.fn()
  const success = vi.fn()
  const wrapper = mount(component, { global: {
    plugins: [store],
    mocks: { $t: key => key, $i18n: { t: key => key }, $success: success, $router: { push }, $filters: { localtime: value => value } },
    stubs: { ...Object.fromEntries(['Row', 'Col', 'Select', 'Option', 'Upload', 'Icon', 'Modal', 'Button', 'ButtonGroup', 'Card', 'Tag', 'Alert', 'Spin'].map(name => [name, Slot])), Form, FormItem, Input }
  } })
  wrappers.push(wrapper)
  return { wrapper, store, push, success }
}
const input = (wrapper, label) => wrapper.get(`[data-label="m.${label}"] input`)
beforeEach(() => { for (const list of Object.values(requests)) list.length = 0 })
afterEach(() => { for (const wrapper of wrappers.splice(0)) wrapper.unmount(); vi.useRealTimers() })

test('cold profile settings fill real inputs when profile arrives after mount', async () => {
  const { wrapper, store } = setup(ProfileSetting)
  expect(input(wrapper, 'Real_Name').element.value).toBe('')
  store.commit('profile', { profile: profile() }); await flushPromises()
  expect(input(wrapper, 'Real_Name').element.value).toBe('同学1')
  expect(input(wrapper, 'Class_Name').element.value).toBe('厦门大学')
  expect(input(wrapper, 'Major').element.value).toBe('软件工程')
  expect(wrapper.vm.formProfile.language).toBe('zh-CN')
})

test('same-account refresh and delayed save do not overwrite unsaved edits', async () => {
  const { wrapper, store } = setup(ProfileSetting, profile())
  await input(wrapper, 'Major').setValue('用户正在编辑')
  store.commit('profile', { profile: profile(1, { major: '服务端更新', mood: '新签名' }) }); await flushPromises()
  expect(input(wrapper, 'Major').element.value).toBe('用户正在编辑')
  expect(input(wrapper, 'Mood').element.value).toBe('新签名')
  wrapper.vm.updateProfile()
  await input(wrapper, 'Major').setValue('保存期间继续编辑')
  requests.updateProfile[0].resolve({ data: { data: profile(1, { major: '用户正在编辑', mood: '新签名' }) } })
  await flushPromises()
  expect(input(wrapper, 'Major').element.value).toBe('保存期间继续编辑')
  expect(wrapper.vm.loadingSaveBtn).toBe(false)
})

test('account change/logout clears old form/avatar state and discards old saves', async () => {
  const { wrapper, store, success } = setup(ProfileSetting, profile())
  await input(wrapper, 'Major').setValue('旧账号草稿')
  await wrapper.setData({ avatarOption: { imgSrc: 'data:image/png;base64,old' }, uploadImgSrc: 'old preview', uploadModalVisible: true, preview: { w: 10, h: 10 } })
  wrapper.vm.updateProfile()
  store.commit('profile', { profile: profile(2, { major: '', mood: '' }) }); await flushPromises()
  expect(input(wrapper, 'Real_Name').element.value).toBe('同学2')
  expect(input(wrapper, 'Major').element.value).toBe('')
  expect(wrapper.vm.avatarOption.imgSrc).toBe('')
  expect(wrapper.vm.uploadImgSrc).toBe('')
  expect(wrapper.vm.uploadModalVisible).toBe(false)
  requests.updateProfile[0].resolve({ data: { data: profile(1) } }); await flushPromises()
  expect(store.getters.user.id).toBe(2)
  expect(success).not.toHaveBeenCalled()
  store.commit('profile', { profile: {} }); await flushPromises()
  expect(Object.values(wrapper.vm.formProfile).every(value => value === '')).toBe(true)
})

test('queued old save cannot restore an old account before the identity watcher flushes', async () => {
  const { wrapper, store } = setup(ProfileSetting, profile())
  wrapper.vm.updateProfile()
  await flushPromises()
  requests.updateProfile[0].resolve({ data: { data: profile(1) } })
  store.commit('profile', { profile: profile(2) })
  await flushPromises()
  expect(store.getters.user.id).toBe(2)
  expect(input(wrapper, 'Real_Name').element.value).toBe('同学2')
})

test('account email initializes late, and account switch cancels old password logout timer', async () => {
  vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] })
  const { wrapper, store, push } = setup(AccountSetting)
  expect(input(wrapper, 'Old_Email').element.value).toBe('')
  store.commit('profile', { profile: profile() }); await flushPromises()
  expect(input(wrapper, 'Old_Email').element.value).toBe('user1@example.test')
  await input(wrapper, 'New_Email').setValue('draft@example.test')
  wrapper.vm.changePassword(); await flushPromises()
  requests.changePassword[0].resolve({ data: { data: null } }); await flushPromises()
  store.commit('profile', { profile: profile(2) }); await flushPromises()
  expect(input(wrapper, 'New_Email').element.value).toBe('')
  expect(input(wrapper, 'Old_Email').element.value).toBe('user2@example.test')
  vi.advanceTimersByTime(6000)
  expect(push).not.toHaveBeenCalled()
})

test('security settings wait for identity and reject late sessions/QR after account switch or unmount', async () => {
  const { wrapper, store } = setup(SecuritySetting)
  expect(requests.getSessions).toHaveLength(0)
  store.commit('profile', { profile: profile() }); await flushPromises()
  expect(requests.getSessions).toHaveLength(1)
  store.commit('profile', { profile: profile(2) }); await flushPromises()
  requests.getSessions[0].resolve({ data: { data: [{ session_key: 'old', current_session: true, user_agent: '' }] } })
  requests.twoFactorAuth[0].resolve({ data: { data: 'old QR' } }); await flushPromises()
  expect(wrapper.vm.sessions).toEqual([])
  expect(wrapper.vm.qrcodeSrc).toBe('')
  requests.getSessions[1].resolve({ data: { data: [{ session_key: 'current', current_session: true, user_agent: '', last_activity: '' }] } })
  requests.twoFactorAuth[1].resolve({ data: { data: 'new QR' } }); await flushPromises()
  expect(wrapper.vm.sessions[0].session_key).toBe('current')
  expect(wrapper.vm.qrcodeSrc).toBe('new QR')
  wrapper.vm.getSessions()
  wrapper.unmount()
  requests.getSessions[2].resolve({ data: { data: [{ session_key: 'after unmount' }] } }); await flushPromises()
  expect(wrapper.vm.sessions[0].session_key).toBe('current')
})
