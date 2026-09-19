// Run after npm run build. This reads existing artifacts and never rebuilds them.
import assert from 'node:assert/strict'
import { existsSync, readFileSync, readdirSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '../dist')
const checked = new Set()
const localAsset = url => {
  const clean = url.replace(/^['"]|['"]$/g, '').split(/[?#]/)[0]
  if (!clean || /^(data:|blob:)/.test(clean)) return null
  // Absolute CDN URLs still map to this same static build directory.
  if (clean.includes('/static/')) return join(root, clean.slice(clean.indexOf('/static/')))
  if (/^(https?:|\/public\/)/.test(clean)) return null
  return resolve(root, 'static', clean)
}
for (const [html, entry] of [['index.html', 'oj-'], ['admin/index.html', 'admin-']]) {
  const source = readFileSync(join(root, html), 'utf8')
  assert(source.includes('type="module"'), html + ' must be a Vue 3/Vite entry')
  assert(source.includes('/static/' + entry), html + ' must load its own application entry')
  for (const match of source.matchAll(/(?:src|href)="([^"]+)"/g)) {
    if (!match[1].includes('/static/')) continue
    const target = localAsset(match[1])
    assert(existsSync(target), 'Missing HTML asset: ' + match[1])
    checked.add(target)
  }
}
function walk (directory) {
  return readdirSync(directory, { withFileTypes: true }).flatMap(entry => entry.isDirectory() ? walk(join(directory, entry.name)) : [join(directory, entry.name)])
}
for (const file of walk(join(root, 'static'))) {
  assert(!/vendor\.dll\./.test(file), 'Webpack Vue 2 DLL must not survive in dist')
  if (file.endsWith('.css')) {
    const source = readFileSync(file, 'utf8')
    for (const match of source.matchAll(/url\(([^)]+)\)/g)) {
      const raw = match[1].replace(/^['"]|['"]$/g, '').split(/[?#]/)[0]
      const target = raw.includes('/static/') ? localAsset(raw) : /^(data:|https?:|\/public\/|#)/.test(raw) || !raw ? null : resolve(dirname(file), raw)
      if (target) { assert(existsSync(target), 'Missing CSS/font asset: ' + file + ' -> ' + raw); checked.add(target) }
    }
  }
  if (file.endsWith('.js')) {
    const source = readFileSync(file, 'utf8')
    for (const marker of ['MOCK-NOT-A-REAL-TOKEN', '/__mock/session', 'mock_student', 'Vue.js v2.']) assert(!source.includes(marker), 'Production includes mock/legacy marker: ' + marker)
  }
}
console.log('PASS production OJ/admin entries, ' + checked.size + ' linked assets/fonts, no Mock fixtures or Vue 2 DLL.')
