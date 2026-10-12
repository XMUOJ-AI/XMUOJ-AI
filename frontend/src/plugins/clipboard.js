const handlers = new WeakMap()
function copy (text) {
  if (navigator.clipboard && window.isSecureContext) return navigator.clipboard.writeText(text)
  const input = document.createElement('textarea')
  input.value = text
  input.style.position = 'fixed'
  input.style.opacity = '0'
  document.body.appendChild(input)
  input.select()
  const succeeded = document.execCommand('copy')
  input.remove()
  return succeeded ? Promise.resolve() : Promise.reject(new Error('Copy failed'))
}
export default {
  install (app) {
    app.directive('clipboard', {
      mounted (el, binding) {
        let state = handlers.get(el)
        if (!state) {
          state = { callbacks: {} }
          state.listener = () => copy(String(state.callbacks.copy ?? '')).then(() => state.callbacks.success?.(), error => state.callbacks.error?.(error))
          handlers.set(el, state)
          el.addEventListener('click', state.listener)
        }
        state.callbacks[binding.arg] = binding.value
      },
      updated (el, binding) { const state = handlers.get(el); if (state) state.callbacks[binding.arg] = binding.value },
      unmounted (el) { const state = handlers.get(el); if (state) el.removeEventListener('click', state.listener); handlers.delete(el) }
    })
  }
}
