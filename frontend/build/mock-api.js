'use strict'

const express = require('express')

module.exports = function () {
  const router = express.Router()
  router.use(express.json({ limit: '1mb' }))
  const accounts = {
    student: { id: 1, username: 'mock_student', real_name: '模拟同学', email: 'student@example.test', admin_type: 'Regular User', problem_permission: 'None' },
    other: { id: 3, username: 'mock_other', real_name: '另一位同学', email: 'other@example.test', admin_type: 'Regular User', problem_permission: 'None' },
    admin: { id: 2, username: 'mock_admin', real_name: '模拟管理员', email: 'admin@example.test', admin_type: 'Super Admin', problem_permission: 'All' }
  }
  const user = Object.assign({}, accounts.student)
  let loggedIn = true
  const profile = { user, real_name: '模拟同学', avatar: '/static/default.png', language: 'zh-CN', school: '厦门大学', major: '软件工程', mood: 'Mock 前端预览', accepted_number: 2, submission_number: 5, total_score: 200, acm_problems_status: { problems: { 1: { _id: '1001', status: 0 }, 2: { _id: '1002', status: 0 } } }, oi_problems_status: { problems: {} } }
  const problems = [
    ['1001', 'A + B（模拟题目）', 'Low', ['模拟'], '<p>输入两个整数 a 和 b，输出它们的和。</p>', '1 2', '3'],
    ['1002', '迷宫最短路（BFS）', 'Mid', ['BFS', '图论'], '<p>给定一个由 0 和 1 组成的 n × m 网格，0 为道路，1 为障碍。求从左上角到右下角的最少移动次数，每步可向上下左右移动。</p>', '2 2\n0 0\n1 0', '2'],
    ['1003', '连通区域（DFS）', 'Mid', ['DFS', '图论'], '<p>给定 n × m 的二进制网格，统计由上下左右相邻的 1 组成的连通区域数量。</p>', '2 3\n1 0 1\n1 0 1', '2']
  ].map((p, i) => ({ id: i + 1, _id: p[0], title: p[1], difficulty: p[2], tags: p[3], description: p[4], input_description: '<p>输入格式见题面和样例。</p>', output_description: '<p>输出一个整数。</p>', samples: [{ input: p[5], output: p[6] }], hint: '<p>这是用于页面预览的模拟题目，提交不会执行真实判题。</p>', source: '本地 Mock', created_by: user, create_time: '2026-09-09T01:00:00Z', last_update_time: '2026-09-09T01:00:00Z', time_limit: 1000, memory_limit: 128, languages: ['C++', 'Python3'], template: { 'C++': '#include <iostream>\nusing namespace std;\nint main() {\n    return 0;\n}', Python3: '# 请在这里编写代码\n' }, io_mode: { io_mode: 'Standard IO', input: 'input.txt', output: 'output.txt' }, rule_type: 'ACM', spj: false, visible: true, submission_number: 10, accepted_number: 6, statistic_info: { '0': 6, '-1': 4 }, my_status: null, total_score: 100 }))
  const makeSubmission = (id, problem, code, result, timestamp = new Date().toISOString()) => ({ id, problem: problem.id, problem_id: problem._id, problem_title: problem.title, username: user.username, user_id: user.id, language: 'C++', code, result, create_time: timestamp, statistic_info: { time_cost: 8, memory_cost: 1048576 }, info: { data: [{ test_case: '1', result, cpu_time: 8, real_time: 10, memory: 1048576 }] }, shared: false, can_unshare: true, code_length: code.length })
  const submissions = [makeSubmission('mock-001', problems[0], '// 模拟记录，不是真实判题\nint main() { return 0; }', 0, '2026-09-19T06:00:00Z')]
  const ok = (res, data) => res.json({ error: null, data })
  const fail = (res, message) => res.json({ error: 'mock_error', data: message })
  const page = (req, rows) => ({ total: rows.length, results: rows.slice(Number(req.query.offset) || 0, (Number(req.query.offset) || 0) + (Number(req.query.limit) || 20)) })
  router.get('/website', (req, res) => ok(res, { website_name: 'XMUOJ · MOCK', website_name_shortcut: 'XMUOJ', website_footer: '本地 Mock 预览 · 所有题目、账号和判题结果均为模拟数据', allow_register: false, languages: ['C++', 'Python3'], time_zone: 'Asia/Shanghai' }))
  const setSession = role => {
    loggedIn = role !== 'guest'
    Object.assign(user, accounts[role] || accounts.student)
    profile.real_name = user.real_name
    return loggedIn ? profile : null
  }
  router.get('/profile', (req, res) => {
    if (req.query.username && req.query.username !== user.username) {
      if (!loggedIn || user.admin_type !== 'Super Admin') return res.status(403).json({ error: 'permission_denied', data: 'Mock profile permission denied' })
      const account = Object.values(accounts).find(item => item.username === req.query.username)
      return ok(res, account ? Object.assign({}, profile, { user: account, real_name: account.real_name }) : null)
    }
    ok(res, loggedIn ? profile : null)
  })
  router.post('/login', (req, res) => { setSession(req.body.username === 'mock_admin' ? 'admin' : req.body.username === 'mock_other' ? 'other' : 'student'); ok(res, 'Mock login succeeded') })
  // This router exists only in the loopback-only development mock server.
  router.post('/__mock/session', (req, res) => {
    if (!['student', 'other', 'admin', 'guest'].includes(req.body.role)) return res.status(400).json({ error: 'invalid_role', data: 'Unknown mock role' })
    ok(res, setSession(req.body.role))
  })
  router.get('/logout', (req, res) => { loggedIn = false; ok(res, null) })
  router.post('/tfa_required', (req, res) => ok(res, { result: false }))
  router.get('/languages', (req, res) => ok(res, {
    languages: ['C++', 'Python3'].map(name => ({
      name,
      description: name + ' (Mock)',
      content_type: name === 'C++' ? 'text/x-c++src' : 'text/x-python',
      config: {
        compile: { src_name: name === 'C++' ? 'main.cpp' : 'main.py', exe_name: name === 'C++' ? 'main' : '__pycache__/main.pyc', compile_command: name === 'C++' ? 'g++ -O2 -std=c++17 main.cpp -o main (Mock only)' : 'python3 -m py_compile main.py (Mock only)' },
        run: { command: name === 'C++' ? './main (Mock only)' : 'python3 main.py (Mock only)' },
        template: name === 'C++' ? '// PREPEND BEGIN\n// PREPEND END\n// TEMPLATE BEGIN\nint main() { return 0; }\n// TEMPLATE END\n// APPEND BEGIN\n// APPEND END' : '# TEMPLATE BEGIN\n# TEMPLATE END'
      }
    })),
    spj_languages: [{ name: 'C', description: 'C (Mock)', content_type: 'text/x-csrc' }, { name: 'C++', description: 'C++ (Mock)', content_type: 'text/x-c++src' }]
  }))
  // Static display fixture only; no challenge validation or email delivery occurs.
  router.get('/captcha', (req, res) => ok(res, 'data:image/svg+xml;base64,' + Buffer.from('<svg xmlns="http://www.w3.org/2000/svg" width="160" height="42"><rect width="160" height="42" fill="#f3f5f7"/><text x="25" y="28" font-family="monospace" font-size="24" fill="#495060">MOCK</text></svg>').toString('base64')))
  router.get('/announcement', (req, res) => ok(res, page(req, [{ id: 1, title: 'Mock 模式已开启：可浏览题库与模拟提交', content: '<p>本地模拟环境已启动。默认登录 mock_student；提交仅生成内存中的演示记录，重启后恢复初始数据。</p>', created_by: user, create_time: '2026-09-09T01:00:00Z' }])))
  router.get('/problem/tags', (req, res) => ok(res, ['BFS', 'DFS', '图论', '模拟'].map((name, i) => ({ id: i + 1, name, problem_count: problems.filter(p => p.tags.includes(name)).length }))))
  router.get('/problem', (req, res) => {
    if (req.query.problem_id) {
      const problem = problems.find(p => p._id === req.query.problem_id)
      return problem ? ok(res, problem) : fail(res, '模拟题目不存在')
    }
    const rows = problems.filter(p => (!req.query.keyword || (p.title + p._id).includes(req.query.keyword)) && (!req.query.difficulty || p.difficulty === req.query.difficulty) && (!req.query.tag || p.tags.includes(req.query.tag)))
    ok(res, page(req, rows))
  })
  router.get('/pickone', (req, res) => ok(res, problems[Math.floor(Math.random() * problems.length)]._id))
  router.get('/submission_exists', (req, res) => ok(res, submissions.some(s => String(s.problem) === req.query.problem_id)))
  router.get('/submissions', (req, res) => ok(res, page(req, submissions.filter(s => (!req.query.problem_id || s.problem_id === req.query.problem_id) && (!req.query.username || s.username === req.query.username) && (req.query.result === undefined || req.query.result === '' || String(s.result) === req.query.result)))))
  router.get('/submission', (req, res) => { const s = submissions.find(s => s.id === req.query.id); return s ? ok(res, s) : fail(res, '模拟提交不存在') })
  router.post('/submission', (req, res) => {
    if (!loggedIn) return fail(res, 'Please login to the mock environment')
    if (req.body.contest_id && (!contextCanSubmit || !contextCanSubmit(req.body.contest_id))) return res.status(403).json({ error: 'permission_denied', data: 'Mock contest submission unavailable' })
    const problem = problems.find(p => String(p.id) === String(req.body.problem_id) || p._id === String(req.body.problem_id))
    if (!problem) return fail(res, '模拟题目不存在')
    const submission = makeSubmission('mock-' + (submissions.length + 1), problem, req.body.code || '', 0)
    submission.language = req.body.language || 'C++'
    submissions.unshift(submission)
    ok(res, { submission_id: submission.id })
  })
  const { canSubmit: contextCanSubmit } = require('./mock-site')(router, { user, accounts, profile, isLoggedIn: () => loggedIn, problems, submissions, ok, fail, page })
  require('./mock-learning-path')(router, problems, submissions, () => loggedIn)
  const aiContext = { user, isLoggedIn: () => loggedIn, problems, submissions }
  require('./mock-learning-feedback')(router, aiContext)
  require('./mock-problem-guidance')(router, aiContext)
  require('./mock-submission-analysis')(router, aiContext)
  router.use((req, res) => fail(res, `Mock 尚未实现 ${req.method} ${req.path}`))
  return router
}
