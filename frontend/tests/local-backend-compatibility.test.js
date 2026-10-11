import { beforeEach, describe, expect, test, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { h } from 'vue'
import User from '../src/pages/admin/views/general/User.vue'
import adminApi from '../src/pages/admin/api'
import ojApi from '../src/pages/oj/api'
import axios from 'axios'

vi.mock('../src/pages/admin/router', () => ({ default: { push: vi.fn() } }))
vi.mock('../src/pages/oj/router', () => ({ default: { push: vi.fn() } }))
vi.mock('axios', () => {
  const client = Object.assign(vi.fn(), { defaults: {}, get: vi.fn() })
  return { default: client }
})

beforeEach(() => { axios.mockReset(); axios.get.mockReset() })

describe('preserved local backend contracts', () => {
  test('rejudge is a CSRF-protected POST with the submission in the body', async () => {
    axios.mockResolvedValue({ data: { error: null, data: {} } })
    await ojApi.submissionRejudge('submission-1')
    expect(axios).toHaveBeenCalledWith(expect.objectContaining({
      url: 'admin/submission/rejudge', method: 'post', data: { id: 'submission-1' }
    }))
    expect(axios.defaults.xsrfHeaderName).toBe('X-CSRFToken')
  })

  test('private credentials accept XLSX and reject JSON error responses', async () => {
    const blob = new Blob(['private credentials'])
    axios.get.mockResolvedValue({ headers: { 'content-type': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' }, data: blob })
    expect(await adminApi.downloadUserCredentials('export-1')).toBe(blob)
    expect(axios.get).toHaveBeenCalledWith('admin/generate_user', { params: { file_id: 'export-1' }, responseType: 'blob' })
    axios.get.mockResolvedValue({ headers: { 'content-type': 'application/json' }, data: new Blob(['{"error":"permission-denied"}']) })
    await expect(adminApi.downloadUserCredentials('export-1')).rejects.toThrow('不可用或已过期')
  })

  test('Vue 3 renders credential row actions and downloads the selected export', async () => {
    const exported = { file_id: 'export-1', created_count: 2, created_at: '2026-10-11', expires_at: '2026-10-12' }
    const Container = { setup (_, { slots }) { return () => h('div', [slots.title?.(), slots.default?.()]) } }
    const Table = { props: ['data'], setup (props, { slots }) { return () => h('div', slots.default?.().map(vnode => h(vnode, { row: props.data[0] }))) } }
    const Column = { props: ['row'], setup (props, { slots }) { return () => h('div', props.row ? slots.default?.({ row: props.row }) : []) } }
    const Button = { emits: ['click'], setup (_, { emit, slots }) { return () => h('button', { onClick: () => emit('click') }, slots.default?.()) } }
    const download = vi.fn()
    const component = { ...User, mounted () {}, methods: { ...User.methods, downloadCredentials: download } }
    const wrapper = mount(component, {
      data: () => ({ credentialExports: [exported] }),
      global: {
        mocks: { $t: text => text, $filters: { localtime: text => text } },
        directives: { loading: () => {} },
        stubs: {
          Panel: Container, 'el-table': Table, 'el-table-column': Column, 'el-button': Button,
          'el-row': Container, 'el-col': Container, 'el-popover': Container, 'el-form': true,
          'el-upload': true, 'el-input': true, 'el-pagination': true, 'el-dialog': true
        }
      }
    })
    const button = wrapper.findAll('button').find(item => item.text() === '下载凭据')
    expect(button).toBeDefined()
    await button.trigger('click')
    expect(download).toHaveBeenCalledWith('export-1')
    wrapper.unmount()
  })

  test('import without new users keeps passwords and avoids credential download', async () => {
    axios.mockResolvedValue({ data: { error: null, data: { file_id: null } } })
    const state = {
      uploadUsers: [['student', '学生', '班级']], loadingImport: false,
      getUserList: vi.fn(), refreshCredentialExports: vi.fn(), downloadCredentials: vi.fn(),
      handleResetData: vi.fn(), $message: vi.fn()
    }
    User.methods.handleUsersUpload.call(state)
    await flushPromises()
    expect(state.loadingImport).toBe(false)
    expect(state.downloadCredentials).not.toHaveBeenCalled()
    expect(state.$message).toHaveBeenCalledWith(expect.stringContaining('已有账号密码保持不变'))
    expect(state.refreshCredentialExports).toHaveBeenCalledOnce()
  })
})
