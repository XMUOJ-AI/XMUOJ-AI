'use strict'

// Deterministic browser acceptance fixtures. Mounted only by mock-api, never by production.
module.exports = function (router, context) {
  const { user, accounts, profile, isLoggedIn, problems, submissions, ok, page } = context
  const now = '2026-09-19T06:00:00Z'
  const admin = () => isLoggedIn() && user.admin_type === 'Super Admin'
  const denied = (res, status = 403) => res.status(status).json({ error: status === 401 ? 'not_authenticated' : 'permission_denied', data: status === 401 ? 'Please login first' : 'Mock permission denied' })
  const logged = (req, res, next) => isLoggedIn() ? next() : denied(res, 401)
  const adminOnly = (req, res, next) => admin() ? next() : denied(res, isLoggedIn() ? 403 : 401)
  const clone = value => JSON.parse(JSON.stringify(value))
  const users = Object.values(accounts).map(account => Object.assign({ is_disabled: false, create_time: now, last_login: now, two_factor_auth: false, open_api: false }, clone(account)))
  const contests = [
    { id: 1, title: '图的遍历练习（Mock ACM）', rule_type: 'ACM', contest_type: 'Public', status: '0', start_time: '2026-09-19T01:00:00Z', end_time: '2026-09-19T12:00:00Z' },
    { id: 2, title: '基础算法实验（Mock OI）', rule_type: 'OI', contest_type: 'Public', status: '-1', start_time: '2026-09-18T01:00:00Z', end_time: '2026-09-18T12:00:00Z' },
    { id: 3, title: '私有班级练习（口令 mock123）', rule_type: 'ACM', contest_type: 'Password Protected', status: '0', start_time: '2026-09-19T01:00:00Z', end_time: '2026-09-19T12:00:00Z', password: 'mock123' },
    { id: 4, title: '即将开始的实验（Mock）', rule_type: 'ACM', contest_type: 'Public', status: '1', start_time: '2026-09-20T01:00:00Z', end_time: '2026-09-20T12:00:00Z' }
  ].map(item => Object.assign({ description: '<p>用于 Vue 迁移验收的固定实验数据，不进行真实判题。</p>', created_by: clone(accounts.admin), create_time: now, last_update_time: now, now, visible: true, allowed_ip_ranges: [], real_time_rank: true, rank_cache: false, participants: 2 }, item))
  const access = new Set()
  const contestOf = req => contests.find(item => String(item.id) === String(req.query.contest_id || req.query.id || req.body.contest_id || req.body.id))
  const allowed = contest => !!contest && (admin() || (contest.status !== '1' && (contest.contest_type === 'Public' || access.has(user.id + ':' + contest.id))))
  const contestProblems = contest => problems.map(item => Object.assign({}, clone(item), { contest_id: contest.id, rule_type: contest.rule_type, allow_public_test_case_download: false, can_download_test_case: false }))
  const announcements = [{ id: 1, title: 'Mock 实验说明', content: '<p>可测试题目、提交、排名与管理表单，所有修改仅保存在内存。</p>', created_by: clone(accounts.admin), create_time: now, last_update_time: now, visible: true }]
  const tags = ['BFS', 'DFS', '图论', '模拟'].map((name, i) => ({ id: i + 1, name, normalized_name: name.toLowerCase(), aliases: [], rank: i, is_active: true, description: 'Mock 知识点', problem_count: problems.filter(problem => problem.tags.includes(name)).length }))
  problems.forEach((problem, index) => Object.assign(problem, { created_by: clone(accounts.admin), share_submission: true, allow_public_test_case_download: index === 0, can_download_test_case: index === 0, test_case_id: 'mock-case-' + problem.id, test_case_score: [{ input_name: '1.in', output_name: '1.out', score: 100 }], spj_language: 'C', spj_code: '', spj_compile_ok: false, contest_id: null }))
  const website = { website_name: 'XMUOJ · MOCK', website_name_shortcut: 'XMUOJ', website_footer: '本地 Mock 预览', allow_register: false, time_zone: 'Asia/Shanghai', allow_user_register: false, exam_mode: false }
  const smtp = { server: 'smtp.example.test', port: 587, email: 'mock@example.test', password: '', tls: true }
  const download = (res, filename, content = 'Mock fixture only. No real submissions or test data.\n') => res.set({ 'Content-Type': 'text/plain; charset=utf-8', 'Content-Disposition': 'attachment; filename=' + filename }).send(content)
  const notFound = res => res.status(404).json({ error: 'not_found', data: 'Mock record not found' })
  const findProblem = req => problems.find(item => String(item.id) === String(req.query.id || req.query.problem_id || req.body.id) || item._id === String(req.query.problem_id))

  router.get('/contests', (req, res) => ok(res, page(req, contests.filter(item => (!req.query.keyword || item.title.includes(req.query.keyword)) && (!req.query.status || item.status === req.query.status) && (!req.query.rule_type || item.rule_type === req.query.rule_type)))))
  router.get('/contest', (req, res) => { const contest = contestOf(req); return contest ? ok(res, Object.assign({}, contest, { password: undefined })) : notFound(res) })
  router.get('/contest/access', logged, (req, res) => ok(res, { access: allowed(contestOf(req)) }))
  router.post('/contest/password', logged, (req, res) => {
    const contest = contestOf(req)
    if (!contest || req.body.password !== contest.password) return res.json({ error: 'invalid_password', data: 'Wrong mock contest password' })
    access.add(user.id + ':' + contest.id); ok(res, { access: true })
  })
  router.get('/contest/problem', (req, res) => {
    const contest = contestOf(req)
    if (!allowed(contest)) return denied(res)
    const rows = contestProblems(contest)
    const item = rows.find(problem => problem._id === String(req.query.problem_id))
    return req.query.problem_id ? item ? ok(res, item) : notFound(res) : ok(res, rows)
  })
  router.get('/contest/announcement', (req, res) => allowed(contestOf(req)) ? ok(res, announcements) : denied(res))
  router.get('/contest_submissions', logged, (req, res) => allowed(contestOf(req)) ? ok(res, page(req, submissions.map(item => Object.assign({}, item, { contest: Number(req.query.contest_id) })))) : denied(res))
  router.get('/contest_rank', logged, (req, res) => {
    const contest = contestOf(req)
    if (!allowed(contest)) return denied(res)
    if (req.query.download_csv) return admin() ? download(res, 'mock-rank.csv', 'rank,username,score\n1,mock_student,200\n2,mock_other,100\n') : denied(res)
    const rows = [accounts.student, accounts.other].map((account, i) => ({ id: i + 1, user: account, accepted_number: 2 - i, total_time: 1200 + i * 600, total_score: 200 - i * 100, submission_info: contest.rule_type === 'OI' ? { 1: 100, 2: i ? 0 : 100 } : { 1: { is_ac: true, is_first_ac: !i, ac_time: 600 + i * 200, error_number: i }, 2: { is_ac: !i, is_first_ac: !i, ac_time: 1200, error_number: 1 } } }))
    ok(res, page(req, rows))
  })
  const summaries = () => contests.slice(0, 2).map(contest => ({ contest_id: contest.id, contest_title: contest.title, rule_type: contest.rule_type, end_time: contest.end_time, ac_count: 2, total_score: 200, submission_count: 3, my_rank: 1 }))
  router.get('/profile/contests', logged, (req, res) => ok(res, Object.assign(page(req, summaries()), { summary: { contest_count: 2, submission_count: 6, ac_count: 4 } })))
  router.get('/profile/contest_detail', logged, (req, res) => {
    const summary = summaries().find(item => String(item.contest_id) === req.query.contest_id)
    if (!summary) return notFound(res)
    ok(res, Object.assign({}, summary, { problem_items: problems.map(problem => ({ problem_id: problem.id, display_id: problem._id, title: problem.title, status: 0, score: 100, submission_count: 1, accepted: true })) }))
  })
  router.post('/profile/contest_calibrate', logged, (req, res) => ok(res, { message: 'Mock data refreshed', updated: true }))
  router.put('/profile', logged, (req, res) => { for (const key of ['real_name', 'school', 'major', 'mood', 'language', 'blog', 'github']) if (Object.prototype.hasOwnProperty.call(req.body, key)) profile[key] = req.body[key]; ok(res, profile) })
  router.get('/user_rank', (req, res) => ok(res, page(req, [Object.assign({}, profile, { user: clone(accounts.student) }), Object.assign({}, profile, { user: clone(accounts.other), accepted_number: 1, total_score: 100 })])))
  router.get('/sessions', logged, (req, res) => ok(res, [{ session_key: 'mock-session', ip: '127.0.0.1', last_activity: now, user_agent: 'Mozilla/5.0 Chrome/126.0.0.0 Safari/537.36', current_session: true }]))
  router.delete('/sessions', logged, (req, res) => ok(res, null))
  router.post('/upload_avatar', logged, (req, res) => ok(res, { avatar: '/static/default.png' }))
  router.get('/dl_test_case', (req, res) => { const problem = findProblem(req); return problem && problem.can_download_test_case ? download(res, 'mock-test-case.txt', '1.in: 1 2\n1.out: 3\n') : denied(res) })
  for (const endpoint of ['change_password', 'change_email', 'two_factor_auth', 'apply_reset_password', 'reset_password']) router.post('/' + endpoint, logged, (req, res) => ok(res, { enabled: false }))
  router.get('/two_factor_auth', logged, (req, res) => ok(res, 'data:image/svg+xml;base64,' + Buffer.from('<svg xmlns="http://www.w3.org/2000/svg" width="180" height="180"><rect width="180" height="180" fill="#f3f5f7"/><text x="28" y="95" font-family="monospace" font-size="26" fill="#495060">MOCK QR</text></svg>').toString('base64')))
  router.put('/submission', logged, (req, res) => { const item = submissions.find(submission => submission.id === req.body.id); if (!item || (item.user_id !== user.id && !admin())) return denied(res); item.shared = !!req.body.shared; ok(res, item) })

  // Permission checks cover uploads/downloads as well as JSON list and mutation endpoints.
  router.use('/admin', adminOnly)
  router.get('/admin/dashboard_info', (req, res) => ok(res, { user_count: users.length, recent_contest_count: contests.length, today_submission_count: submissions.length, judge_server_count: 1, env: { FORCE_HTTPS: false, STATIC_CDN_HOST: '' } }))
  router.get('/admin/versions', (req, res) => ok(res, { local_version: 'mock', update: [{ version: 'mock', title: 'Vue 迁移验收 Mock', level: 'info', details: ['所有操作只修改本地进程内数据。'] }] }))
  for (const path of ['/admin/announcement', '/admin/contest/announcement']) {
    router.get(path, (req, res) => ok(res, path === '/admin/contest/announcement' ? announcements : page(req, announcements)))
    router.post(path, (req, res) => { const item = Object.assign({ id: announcements.length + 1, created_by: clone(user), create_time: now, last_update_time: now }, req.body); announcements.push(item); ok(res, item) })
    router.put(path, (req, res) => { const item = announcements.find(row => row.id === req.body.id); if (!item) return notFound(res); Object.assign(item, req.body); ok(res, item) })
    router.delete(path, (req, res) => { const index = announcements.findIndex(row => String(row.id) === req.query.id); if (index >= 0) announcements.splice(index, 1); ok(res, null) })
  }
  for (const [path, rows] of [['/admin/user', users], ['/admin/contest', contests], ['/admin/problem', problems], ['/admin/contest/problem', problems]]) {
    router.get(path, (req, res) => {
      if (req.query.id) { const item = rows.find(row => String(row.id) === req.query.id); return item ? ok(res, item) : notFound(res) }
      ok(res, page(req, rows.filter(row => !req.query.keyword || JSON.stringify(row).includes(req.query.keyword))))
    })
    router.post(path, (req, res) => {
      if (path === '/admin/user' && Array.isArray(req.body.users)) {
        for (const row of req.body.users) users.push(Object.assign({}, clone(accounts.student), { id: Math.max(...users.map(item => item.id)) + 1, username: row[0], email: row[2] || '', is_disabled: false, create_time: now }))
        return ok(res, null)
      }
      const item = Object.assign({}, clone(rows[0] || {}), req.body, { id: Math.max(0, ...rows.map(row => row.id)) + 1 }); rows.push(item); ok(res, item)
    })
    router.put(path, (req, res) => { const item = rows.find(row => String(row.id) === String(req.body.id)); if (!item) return notFound(res); Object.assign(item, req.body); ok(res, item) })
    router.delete(path, (req, res) => { const ids = String(req.query.id || '').split(','); for (let i = rows.length - 1; i >= 0; i--) if (ids.includes(String(rows[i].id))) rows.splice(i, 1); ok(res, null) })
  }
  router.get('/admin/problem/tags', (req, res) => {
    if (req.query.id) return ok(res, tags.find(tag => String(tag.id) === req.query.id) || null)
    ok(res, tags.filter(tag => (!req.query.keyword || tag.name.includes(req.query.keyword)) && (req.query.include_inactive === 'true' || tag.is_active) && (req.query.only_used !== 'true' || tag.problem_count > 0)))
  })
  router.post('/admin/problem/tags', (req, res) => { const item = Object.assign({ id: Math.max(0, ...tags.map(tag => tag.id)) + 1, aliases: [], is_active: true, problem_count: 0, normalized_name: String(req.body.name || '').toLowerCase() }, req.body); tags.push(item); ok(res, item) })
  router.put('/admin/problem/tags', (req, res) => { const item = tags.find(tag => tag.id === req.body.id); if (!item) return notFound(res); Object.assign(item, req.body); ok(res, item) })
  router.delete('/admin/problem/tags', (req, res) => { const index = tags.findIndex(tag => String(tag.id) === req.query.id); if (index >= 0) tags.splice(index, 1); ok(res, null) })
  router.get('/admin/problem/tag_audit', (req, res) => ok(res, { summary: { total_tags: tags.length, active_tags: tags.filter(tag => tag.is_active).length, duplicate_groups: 0, zero_problem_tags: 0 }, duplicates: [], zero_problem_tags: [], low_frequency_tags: tags.filter(tag => tag.problem_count < Number(req.query.low_frequency_threshold || 2)), alias_conflicts: [] }))
  router.get('/admin/website', (req, res) => ok(res, website))
  router.post('/admin/website', (req, res) => { Object.assign(website, req.body); ok(res, website) })
  router.get('/admin/smtp', (req, res) => ok(res, smtp))
  for (const method of ['post', 'put']) router[method]('/admin/smtp', (req, res) => { Object.assign(smtp, req.body); ok(res, smtp) })
  router.get('/admin/judge_server', (req, res) => ok(res, { token: 'MOCK-NOT-A-REAL-TOKEN', servers: [{ id: 1, hostname: 'mock-judge', ip: '127.0.0.1', status: 'normal', task_number: 0, cpu_core: 4, cpu_usage: 10, memory_usage: 20, is_disabled: false, judger_version: 'Mock', service_url: 'http://mock.invalid', create_time: now, last_heartbeat: now }] }))
  router.get('/admin/prune_test_case', (req, res) => ok(res, [{ id: 'mock-unused-test-case', create_time: 1789797600 }]))
  router.get('/admin/contest/acm_helper', (req, res) => ok(res, [{ id: 1, username: accounts.student.username, real_name: accounts.student.real_name, problem_id: 1, ac_info: { is_first_ac: true, ac_time: 600 }, checked: false, create_time: now }]))
  router.post('/admin/generate_user', (req, res) => ok(res, { file_id: 'mock-users' }))
  router.get('/admin/generate_user', (req, res) => download(res, 'mock-users.csv', 'username,password\nmock_generated,mock_password\n'))
  for (const path of ['test_case', 'download_submissions', 'export_problem']) router.get('/admin/' + path, (req, res) => download(res, 'mock-' + path + '.txt'))
  router.post('/admin/test_case', (req, res) => ok(res, { id: 'mock-uploaded-case', info: [{ input_name: '1.in', output_name: '1.out', score: 100 }] }))
  router.post('/admin/upload_file', (req, res) => res.json({ success: true, file_path: '/api/admin/test_case?id=1', file_name: 'mock-attachment.txt' }))
  router.post('/admin/upload_image', (req, res) => res.json({ success: true, file_path: '/static/default.png' }))
  for (const path of ['import_problem', 'import_fps']) router.post('/admin/' + path, (req, res) => ok(res, { import_count: 1 }))
  for (const path of ['smtp_test', 'change_userpassword', 'compile_spj', 'contest_problem/make_public', 'contest/add_problem_from_public', 'problem/tag_merge', 'problem/tags/batch_delete']) router.post('/admin/' + path, (req, res) => ok(res, { updated_count: 1, message: 'Mock operation succeeded' }))
  for (const path of ['problem/batch_update', 'problem/tags/batch_update', 'contest/problem/batch_languages', 'contest/acm_helper', 'judge_server']) router.put('/admin/' + path, (req, res) => ok(res, { updated_count: 1 }))
  router.post('/admin/problem/batch_update', (req, res) => ok(res, { updated_count: 1 }))
  for (const path of ['prune_test_case', 'judge_server']) router.delete('/admin/' + path, (req, res) => ok(res, null))
  router.get('/admin/submission/rejudge', (req, res) => ok(res, null))
  return { canSubmit: id => { const contest = contests.find(item => String(item.id) === String(id)); return allowed(contest) && contest.status !== '-1' } }
}
