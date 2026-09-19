import { createRouter, createWebHistory } from 'vue-router'
import routes from './routes'
import storage from '@/utils/storage'
import { STORAGE_KEY } from '@/utils/constants'
import { types, default as store } from '@/store'
import ui from '@/services/ui'

const router = createRouter({
  history: createWebHistory('/'),
  scrollBehavior: (to, from, savedPosition) => savedPosition || { left: 0, top: 0 },
  routes
})
router.beforeEach(to => {
  ui.$Loading.start()
  if (to.matched.some(record => record.meta.requiresAuth) && !storage.get(STORAGE_KEY.AUTHED)) {
    ui.$error('Please login first')
    store.commit(types.CHANGE_MODAL_STATUS, { mode: 'login', visible: true })
    return { name: 'home' }
  }
})
router.afterEach(() => ui.$Loading.finish())
router.onError(() => ui.$Loading.error())
export default router
