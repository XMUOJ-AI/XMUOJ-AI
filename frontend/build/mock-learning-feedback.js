'use strict'

// Local-only proposed contract, mounted under /api before the shared fallback.
module.exports = function (router, context) {
  const { user, isLoggedIn, problems, submissions } = context
  const jobs = new Map()
  const attempts = new Map()
  let sequence = 0
  const ok = (res, data) => res.json({ error: null, data })
  const fail = (res, status, error) => res.status(status).json({ error, data: null })
  const scenario = req => typeof req.query.mock_feedback === 'string' ? req.query.mock_feedback : 'ready'
  const authorized = (req, res) => {
    if (isLoggedIn() && scenario(req) !== 'unauthenticated') return true
    fail(res, 401, 'not_authenticated')
    return false
  }
  const summary = mode => {
    if (mode === 'disabled') return { user_id: user.id, status: 'disabled', capabilities: { can_generate: false }, reason: '当前教学配置未开放学习反馈。' }
    const ownSubmissions = submissions.filter(s => String(s.user_id) === String(user.id))
    // Stable screenshot baseline; user-created submissions can advance the range.
    const end = new Date(ownSubmissions.reduce((latest, submission) => Math.max(latest, Date.parse(submission.create_time) || 0), Date.parse('2026-09-19T06:00:00Z')))
    const start = new Date(end.getTime() - 14 * 86400000)
    const rows = mode === 'empty' ? [] : ownSubmissions.filter(s => Date.parse(s.create_time) >= start.getTime() && Date.parse(s.create_time) <= end.getTime())
    if (!rows.length) return { user_id: user.id, status: 'empty', capabilities: { can_generate: false }, reason: '近 14 天暂无提交，完成练习后再来回顾。' }
    return {
      user_id: user.id,
      status: 'ready',
      capabilities: { can_generate: true },
      range: { start: start.toISOString(), end: end.toISOString() },
      submission_count: rows.length,
      evidence: rows.slice(0, 20).map(s => {
        const problem = problems.find(p => String(p._id) === String(s.problem_id))
        const labels = { '-2': '编译错误', '-1': '答案错误', '0': '通过', '1': '时间超限', '2': '时间超限', '3': '内存超限', '4': '运行错误', '5': '系统异常', '6': '等待评测', '7': '评测中', '8': '部分通过', '9': '提交中' }
        const result = Object.prototype.hasOwnProperty.call(labels, s.result) ? labels[s.result] : '评测状态待确认'
        return { id: s.id, occurred_at: s.create_time, text: `${s.problem_id} · ${problem ? problem.title : '题目暂不可用'} · ${result}（模拟记录）` }
      })
    }
  }
  const result = job => {
    const base = { user_id: job.userId, generation_id: job.id, status: 'ready' }
    if (job.mode === 'generating' || Date.now() < job.readyAt) return { ...base, status: 'generating' }
    if (job.mode === 'failed' || job.firstFailure) return { ...base, status: 'failed', message: '模拟生成服务暂时失败，可以重新生成。' }
    if (job.mode === 'insufficient') return { ...base, status: 'insufficient', message: '近期记录或可检索资料不足，暂不能形成可靠反馈。先补充练习，再回来回顾。' }
    if (job.mode === 'unknown') return { ...base, status: 'future_state' }
    const source = (id, title, excerpt) => ({ id, title: title + '（模拟资料）', version: '演示版 v1', availability: job.mode === 'unavailable' ? 'unavailable' : 'available', excerpt, reason: '此资料当前不可访问，仅保留引用名称。' })
    return {
      ...base,
      user_id: job.mode === 'invalid' ? 'different-user' : job.userId,
      basis: job.basis,
      overview: `这段时间共有 ${job.basis.submission_count} 次模拟提交。建议先回顾已练习题目的解题过程，再梳理 BFS 与 DFS 的使用场景；现有记录不足以判断知识点掌握程度。`,
      points: [
        { id: 'io', label: '基础输入与输出', assessment: 'insufficient', observation: '可结合 1001「A + B」检查输入读取和输出格式。单题通过不能证明已经掌握，建议用边界输入自检。', source_ids: ['io-note'] },
        { id: 'search', label: 'BFS / DFS', assessment: 'insufficient', observation: '1002「迷宫最短路」对应 BFS，1003「连通区域」对应 DFS。近期样本有限，先比较两种遍历的目标，再安排练习。', source_ids: ['search-note'] }
      ],
      suggestions: [
        { id: 'review-io', action: '用 5 分钟复盘 1001：写下输入、输出约定，手算含 0 和负数的例子并检查类型范围。', source_ids: ['io-note'] },
        { id: 'review-search', action: '用 10 分钟画一个小网格：分别记录 BFS 的队列变化与 DFS 的访问顺序，说明何时标记已访问。然后到学习路径查看后续练习。', source_ids: ['search-note'] }
      ],
      sources: [
        source('io-note', '输入输出自检清单', '模拟教学摘录：先核对输入数量与类型，再检查输出格式。用 0、负数和题面范围内的大数手算验证；一次通过仅说明当前测试结果。'),
        source('search-note', '网格搜索复习卡', '模拟教学摘录：BFS 用队列逐层展开，可求无权图最短步数；DFS 沿一个方向深入，适合遍历连通区域。两者都需检查边界并标记访问，防止重复遍历。')
      ]
    }
  }
  router.get('/learning-feedback', (req, res) => {
    if (!authorized(req, res)) return
    if (scenario(req) === 'load_error') return fail(res, 500, 'unavailable')
    ok(res, summary(scenario(req)))
  })
  router.post('/learning-feedback/generations', (req, res) => {
    if (!authorized(req, res)) return
    const mode = scenario(req)
    if (mode === 'busy') return fail(res, 429, 'busy')
    const basis = summary(mode)
    if (!basis.capabilities.can_generate) return fail(res, 403, 'permission_denied')
    const key = `${user.id}:${mode}`
    attempts.set(key, (attempts.get(key) || 0) + 1)
    const job = { id: 'feedback-' + (++sequence), userId: user.id, mode, basis, readyAt: Date.now() + 1200, firstFailure: mode === 'retry' && attempts.get(key) === 1 }
    jobs.set(job.id, job)
    if (jobs.size > 40) jobs.delete(jobs.keys().next().value)
    ok(res, result(job))
  })
  router.get('/learning-feedback/generations/:id', (req, res) => {
    if (!authorized(req, res)) return
    const job = jobs.get(req.params.id)
    if (!job || String(job.userId) !== String(user.id) || job.mode !== scenario(req)) return fail(res, 404, 'not_found')
    ok(res, result(job))
  })
}
