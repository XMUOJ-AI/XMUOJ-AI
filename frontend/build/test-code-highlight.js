'use strict'

const assert = require('assert')
const fs = require('fs')
const path = require('path')
const vm = require('vm')
const babel = require('babel-core')
let hooks
const numbered = []
const hljs = {
  registerLanguage () {},
  highlightBlock () {},
  initLineNumbersOnLoad () { throw new Error('Global numbering can corrupt other code blocks') },
  lineNumbersBlockSync (target) { target.layers++; numbered.push(target) }
}
const moduleObject = {exports: {}}
const source = fs.readFileSync(path.join(__dirname, '../src/plugins/highlight.js'), 'utf8')
vm.runInNewContext(babel.transform(source, {babelrc: false, presets: ['env']}).code, {
  module: moduleObject,
  exports: moduleObject.exports,
  require: name => name.includes('highlightjs-line-numbers2') ? hljs : {}
})
moduleObject.exports.default.install({directive: (name, value) => { hooks = value }})
const target = {
  layers: 0,
  get textContent () { return this.code },
  set textContent (value) { this.code = value; this.layers = 0 }
}
const element = {querySelectorAll: () => [target]}
hooks.bind(element, {value: 'int main() { return 0; }'})
hooks.componentUpdated(element, {value: 'int main() { return 0; }'})
assert.strictEqual(target.layers, 1, 'updates must not nest line-number tables')
assert.strictEqual(numbered.length, 2)
assert(numbered.every(item => item === target), 'numbering stays within the current directive')
hooks.componentUpdated(element, {value: ''})
assert.strictEqual(target.textContent, '', 'loading a new submission clears old code')
console.log('PASS: scoped synchronous line numbering, repeated updates and empty-code reset')
