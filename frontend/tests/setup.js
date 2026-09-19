import { beforeEach, vi } from 'vitest'

globalThis.__AI_FEATURES_MOCK__ = true
globalThis.__LEARNING_PATH_MOCK__ = true
beforeEach(() => {
  globalThis.__AI_FEATURES_MOCK__ = true
  globalThis.__LEARNING_PATH_MOCK__ = true
  if (typeof window !== 'undefined') window.localStorage.clear()
})
if (typeof window !== 'undefined') {
  window.matchMedia = window.matchMedia || (() => ({ matches: false, addListener () {}, removeListener () {}, addEventListener () {}, removeEventListener () {}, dispatchEvent () {} }))
  window.scrollTo = vi.fn()
}
globalThis.ResizeObserver = class { observe () {} unobserve () {} disconnect () {} }
