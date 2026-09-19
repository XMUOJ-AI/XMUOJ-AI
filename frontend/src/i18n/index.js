import { createI18n } from 'vue-i18n'
import ivEN from 'view-ui-plus/dist/locale/en-US'
import ivCN from 'view-ui-plus/dist/locale/zh-CN'
import ivTW from 'view-ui-plus/dist/locale/zh-TW'
import elEN from 'element-plus/es/locale/lang/en'
import elCN from 'element-plus/es/locale/lang/zh-cn'
import elTW from 'element-plus/es/locale/lang/zh-tw'
import { m as ojEN } from './oj/en-US'
import { m as ojCN } from './oj/zh-CN'
import { m as ojTW } from './oj/zh-TW'
import { m as adminEN } from './admin/en-US'
import { m as adminCN } from './admin/zh-CN'
import { m as adminTW } from './admin/zh-TW'
import time from '@/utils/time'

export const languages = [
  { value: 'en-US', label: 'English', iv: ivEN, el: elEN },
  { value: 'zh-CN', label: '简体中文', iv: ivCN, el: elCN },
  { value: 'zh-TW', label: '繁體中文', iv: ivTW, el: elTW }
]
const appMessages = { 'en-US': { ...ojEN, ...adminEN }, 'zh-CN': { ...ojCN, ...adminCN }, 'zh-TW': { ...ojTW, ...adminTW } }
const messages = Object.fromEntries(languages.map(lang => [lang.value, { m: appMessages[lang.value], ...lang.iv, ...lang.el }]))
export const instance = createI18n({ legacy: false, locale: 'zh-CN', fallbackLocale: 'zh-CN', messages, missingWarn: false, fallbackWarn: false })
time.changeLocale('zh-CN')
// Preserve the non-component translation and locale interface used by the store.
export default {
  install (app) { app.use(instance); app.config.globalProperties.$i18n.t = instance.global.t },
  t (...args) { return instance.global.t(...args) },
  get locale () { return instance.global.locale.value },
  set locale (value) { instance.global.locale.value = value }
}
