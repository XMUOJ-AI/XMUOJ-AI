import vue from 'eslint-plugin-vue'
import globals from 'globals'

export default [
  { ignores: ['dist/**', 'node_modules/**', 'static/**', 'src/assets/**', 'src/plugins/highlightjs-line-numbers2.js', 'src/pages/admin/components/simditor-file-upload.js'] },
  ...vue.configs['flat/essential'],
  { files: ['**/*.{js,mjs,vue}'], languageOptions: { ecmaVersion: 'latest', sourceType: 'module', globals: { ...globals.browser, ...globals.node, ...globals.vitest } }, rules: { 'no-undef': 'error', 'no-unreachable': 'error', 'vue/multi-word-component-names': 'off' } },
  { files: ['build/mock-*.js'], languageOptions: { sourceType: 'commonjs' } }
]
