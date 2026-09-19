import { describe, expect, test, vi } from 'vitest'
import { createMemoryHistory, createRouter, isNavigationFailure, NavigationFailureType } from 'vue-router'
import { createStore } from 'vuex'
import { syncRouteState } from '../src/services/route-state'
import routes from '../src/pages/oj/router/routes'
import adminRouter from '../src/pages/admin/router'

const views = vi.hoisted(() => {
  const component = { render: () => null }
  return Object.fromEntries(['About', 'ACMRank', 'Announcements', 'ApplyResetPassword', 'FAQ', 'Home', 'Logout', 'NotFound', 'OIRank', 'Problem', 'ProblemList', 'ResetPassword', 'SubmissionDetails', 'SubmissionList', 'UserHome', 'Announcement', 'Conf', 'Contest', 'ContestList', 'JudgeServer', 'Login', 'User', 'PruneTestCase', 'Dashboard', 'ProblemImportOrExport', 'ProblemTagGovernance'].map(name => [name, component]))
})
vi.mock('../src/pages/oj/views', () => views)
vi.mock('../src/pages/admin/views', () => views)
vi.mock('../src/pages/oj/views/contest', () => ({ ContestList: views.Home, ContestDetails: views.Home, ContestProblemList: views.Home, ContestRank: views.Home, ACMContestHelper: views.Home }))
vi.mock('../src/pages/oj/views/setting', () => ({ Settings: views.Home, ProfileSetting: views.Home, AccountSetting: views.Home, SecuritySetting: views.Home }))

describe('Router 4 existing URL contracts', () => {
  test('student named routes preserve public and nested paths', () => {
    const router = createRouter({ history: createMemoryHistory(), routes })
    for (const [name, params, path] of [
      ['home', {}, '/'], ['user-home', {}, '/user-home'], ['problem-list', {}, '/problem'],
      ['problem-details', { problemID: '1002' }, '/problem/1002'],
      ['submission-details', { id: 'mock-ac' }, '/status/mock-ac/'],
      ['contest-details', { contestID: '1' }, '/contest/1/'],
      ['contest-problem-list', { contestID: '1' }, '/contest/1/problems'],
      ['contest-problem-details', { contestID: '1', problemID: '1002' }, '/contest/1/problem/1002/'],
      ['contest-submission-list', { contestID: '1' }, '/contest/1/submissions'],
      ['contest-rank', { contestID: '2' }, '/contest/2/rank'],
      ['profile-setting', {}, '/setting/profile'], ['security-setting', {}, '/setting/security'],
      ['acm-rank', {}, '/acm-rank'], ['oi-rank', {}, '/oi-rank']
    ]) expect(router.resolve({ name, params }).path).toBe(path)
    expect(router.resolve('/missing/deep/link').matched).toHaveLength(1)
    expect(router.resolve('/missing/deep/link').matched[0].path).toContain('pathMatch')
  })
  test('AI query context survives replace, duplicate navigation and back', async () => {
    const router = createRouter({ history: createMemoryHistory(), routes })
    const query = { tab: 'learning-path', path: 'p-1', revision: '3', step: 'bfs' }
    await router.push({ name: 'user-home', query })
    await router.push({ name: 'problem-details', params: { problemID: '1002' }, query: { from: 'learning-path', ...query } })
    const duplicate = await router.push(router.currentRoute.value.fullPath)
    expect(isNavigationFailure(duplicate, NavigationFailureType.duplicated)).toBe(true)
    await router.replace({ query: { ...router.currentRoute.value.query, mock_guidance: 'available' } })
    expect(router.currentRoute.value.query.revision).toBe('3')
    await new Promise(resolve => { const stop = router.afterEach(() => { stop(); resolve() }); router.back() })
    expect(router.currentRoute.value.name).toBe('user-home')
    expect(router.currentRoute.value.query).toEqual(query)
  })
  test('admin history base and existing route parameters remain intact', () => {
    for (const [name, params, href] of [
      ['login', {}, '/admin/login'], ['dashboard', {}, '/admin/'], ['problem-list', {}, '/admin/problems'],
      ['edit-problem', { problemId: '1' }, '/admin/problem/edit/1'],
      ['problem-tag-governance', {}, '/admin/problem/tags'],
      ['edit-contest', { contestId: '1' }, '/admin/contest/1/edit'],
      ['edit-contest-problem', { contestId: '1', problemId: '2' }, '/admin/contest/1/problem/2/edit']
    ]) expect(adminRouter.resolve({ name, params }).href).toBe(href)
  })
  test('route store follows confirmed navigation, never an aborted destination', async () => {
    const router = createRouter({ history: createMemoryHistory(), routes })
    const store = createStore({ state: { route: {} }, mutations: { SYNC_ROUTE (state, route) { state.route = route } } })
    const stop = syncRouteState(router, store)
    await router.push('/contest/1/problems')
    expect(store.state.route.params.contestID).toBe('1')
    router.beforeEach(to => to.params.contestID === '2' ? false : undefined)
    const failure = await router.push('/contest/2/problems')
    expect(isNavigationFailure(failure, NavigationFailureType.aborted)).toBe(true)
    expect(router.currentRoute.value.params.contestID).toBe('1')
    expect(store.state.route.params.contestID).toBe('1')
    stop()
    await router.push('/problem/1001')
    expect(store.state.route.params.contestID).toBe('1')
  })
})
