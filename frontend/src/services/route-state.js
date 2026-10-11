export function syncRouteState (router, store) {
  const update = route => store.commit('SYNC_ROUTE', {
    name: route.name, path: route.path, fullPath: route.fullPath,
    params: { ...route.params }, query: { ...route.query }, meta: { ...route.meta }
  })
  update(router.currentRoute.value)
  return router.afterEach((to, from, failure) => {
    if (!failure) update(to)
  })
}
