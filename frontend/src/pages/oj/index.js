import { createApp } from 'vue'
import ViewUIPlus from 'view-ui-plus'
import App from './App.vue'
import router from './router'
import store from '@/store'
import i18n, { instance } from '@/i18n'
import Panel from './components/Panel.vue'
import VerticalMenu from './components/verticalMenu/verticalMenu.vue'
import VerticalMenuItem from './components/verticalMenu/verticalMenu-item.vue'
import LegacyButton from './components/LegacyButton.vue'
import LegacyIcon from '@/components/LegacyIcon.vue'
import Chart from './components/Chart.vue'
import highlight from '@/plugins/highlight'
import katex from '@/plugins/katex'
import clipboard from '@/plugins/clipboard'
import filters from '@/utils/filters'
import ui, { setUI } from '@/services/ui'
import { syncRouteState } from '@/services/route-state'
import { installTelemetry } from '@/services/telemetry'
import '@/assets/legacy-icons/ionicons.css'
import '@/styles/index.less'

const app = createApp(App)
app.use(store).use(i18n)
// Register the library once, substituting only our original visual components.
const components = { Button: LegacyButton, iButton: LegacyButton, Icon: LegacyIcon, Panel }
const registration = Object.create(app)
registration.component = (name, component) => app.component(name, components[name] || component)
ViewUIPlus.install(registration, { i18n: instance })
app.use(highlight).use(katex).use(clipboard)
app.component('ECharts', Chart)
app.component('LegacyIcon', LegacyIcon)
app.component(VerticalMenu.name, VerticalMenu)
app.component(VerticalMenuItem.name, VerticalMenuItem)
const properties = app.config.globalProperties
properties.$filters = filters
properties.$http = ui.$http
properties.$Message.config({ duration: 2 })
properties.$error = text => properties.$Message.error(String(text))
properties.$info = text => properties.$Message.info(String(text))
properties.$success = text => properties.$Message.success(String(text))
setUI(properties)
syncRouteState(router, store)
installTelemetry(app, router)
app.use(router)
router.isReady().then(() => app.mount('#app'))
