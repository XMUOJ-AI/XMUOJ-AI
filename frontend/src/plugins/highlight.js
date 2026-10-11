import cpp from 'highlight.js/lib/languages/cpp'
import python from 'highlight.js/lib/languages/python'
import java from 'highlight.js/lib/languages/java'
import 'highlight.js/styles/atom-one-light.css'
import hljs from './highlightjs-line-numbers2.js'

hljs.registerLanguage('cpp', cpp)
hljs.registerLanguage('java', java)
hljs.registerLanguage('python', python)

function renderCode (el, binding) {
  Array.from(el.querySelectorAll('code')).forEach(target => {
    // Reset even an empty submission, and number only this directive's block.
    // Global asynchronous numbering can wrap already-numbered blocks repeatedly.
    const code = typeof binding.value === 'string' ? binding.value : target.textContent
    target.textContent = code
    if (!code) return
    hljs.highlightBlock(target)
    hljs.lineNumbersBlockSync(target, {singleLine: true})
  })
}

export default {
  install (app) {
    app.directive('highlight', {deep: true, mounted: renderCode, updated: renderCode})
  }
}
