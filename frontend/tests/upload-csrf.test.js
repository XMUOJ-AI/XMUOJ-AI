import { afterEach, describe, expect, test, vi } from 'vitest'
import ImportAndExport from '../src/pages/admin/views/problem/ImportAndExport.vue'
import Problem from '../src/pages/admin/views/problem/Problem.vue'

vi.mock('../src/pages/admin/api', () => ({ default: {} }))
vi.mock('../src/utils/utils', () => ({ default: {} }))
vi.mock('../src/pages/admin/components/Simditor.vue', () => ({ default: {} }))
vi.mock('../src/pages/admin/components/CodeMirror.vue', () => ({ default: {} }))

afterEach(() => { document.cookie = 'csrftoken=; Max-Age=0; path=/' })

describe('problem uploads send current CSRF credentials', () => {
  test.each([['problem', Problem], ['imports', ImportAndExport]])('%s refreshes headers before every upload', (name, component) => {
    const headers = {}
    const state = { uploadHeaders: headers }
    document.cookie = 'csrftoken=first; path=/'
    component.methods.prepareUpload.call(state)
    expect(headers).toEqual({ 'X-CSRFToken': 'first' })
    document.cookie = 'csrftoken=rotated; path=/'
    component.methods.prepareUpload.call(state)
    expect(headers).toEqual({ 'X-CSRFToken': 'rotated' })
    document.cookie = 'csrftoken=; Max-Age=0; path=/'
    component.methods.prepareUpload.call(state)
    expect(headers).toEqual({})
  })
})
