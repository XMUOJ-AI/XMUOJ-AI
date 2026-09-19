import { createApp, reactive, watch } from 'vue'
import ElementPlus, { ElMessage, ElMessageBox, ElNotification, ElLoading } from 'element-plus'
import 'element-plus/dist/index.css'
import App from './App.vue'
import store from '@/store'
import i18n, { instance, languages } from '@/i18n'
import router from './router'
import filters from '@/utils/filters'
import katex from '@/plugins/katex'
import Panel from './components/Panel.vue'
import IconBtn from './components/btn/IconBtn.vue'
import Save from './components/btn/Save.vue'
import Cancel from './components/btn/Cancel.vue'
import LegacyIcon from '@/components/LegacyIcon.vue'
import ui, { setUI } from '@/services/ui'
import { syncRouteState } from '@/services/route-state'
import { installTelemetry } from '@/services/telemetry'
import '@/assets/legacy-icons/element-icons.css'
import './style.less'

const app = createApp(App)
const config = reactive({ locale: languages.find(lang => lang.value === i18n.locale).el })
app.use(store).use(i18n).use(ElementPlus, config).use(katex)
watch(instance.global.locale, locale => { config.locale = (languages.find(lang => lang.value === locale) || languages[1]).el })
for (const component of [Panel, IconBtn, Save, Cancel, LegacyIcon]) app.component(component.name, component)
const properties = app.config.globalProperties
Object.assign(properties, {
  $filters: filters, $http: ui.$http,
  $message: ElMessage, $msgbox: ElMessageBox, $alert: ElMessageBox.alert, $confirm: ElMessageBox.confirm,
  $prompt: ElMessageBox.prompt, $notify: ElNotification, $loading: ElLoading.service,
  $error: message => ElMessage({ message: String(message), type: 'error' }),
  $warning: message => ElMessage({ message: String(message), type: 'warning' }),
  $success: message => ElMessage({ message: String(message || 'Succeeded'), type: 'success' })
})
setUI(properties)
syncRouteState(router, store)
installTelemetry(app, router)
app.use(router)
router.isReady().then(() => app.mount('#app'))
