'use strict'

// Stable versions: submissions update progress, never reorder existing steps.
module.exports = function (router, problems, submissions, isLoggedIn) {
  const ok = (res, data) => res.json({ error: null, data })
  const authorize = res => {
    if (isLoggedIn()) return true
    res.status(401).json({ error: 'not_authenticated', data: 'Please login first' })
    return false
  }
  const makePath = (scenario, revision = 1) => {
    const steps = problems.map((problem, index) => {
      const completed = submissions.some(s => s.problem_id === problem._id && s.result === 0)
      const judging = scenario === 'judging' && index === 1
      return {
        step_id: 'step-' + (index + 1), order: index + 1,
        title: ['基础输入与输出', '广度优先搜索', '深度优先搜索'][index],
        objective: ['正确读取数据并输出计算结果', '使用队列逐层搜索，理解无权图最短路径', '使用访问标记遍历网格，统计连通区域'][index],
        status: judging ? 'judging' : completed ? 'completed' : 'pending',
        explanation_available: true,
        reason_codes: ['practice_knowledge'],
        problems: [{ problem_id: problem.id, display_id: problem._id, title: problem.title, context: { type: 'public' }, availability: scenario === 'unavailable' && index === 1 ? 'unavailable' : 'available', unavailable_reason: '该题暂时下架，可继续练习其他步骤', status: judging ? 'judging' : completed ? 'completed' : 'pending' }]
      }
    })
    const next = steps.find(s => s.status !== 'completed' && s.problems[0].availability === 'available')
    return {
      status: 'ready', kind: scenario === 'starter' ? 'starter' : 'personalized',
      path_id: 'mock-path', revision, generated_at: '2026-09-09T01:00:00Z', based_on_until: '2026-09-09T01:00:00Z',
      summary: scenario === 'starter' ? '先从基础练习了解你的学习情况' : revision === 2 ? '继续巩固图的遍历，关注访问标记' : '建议优先巩固：BFS 与 DFS',
      focus_points: [{ knowledge_id: 'bfs', label: '广度优先搜索', assessment: scenario === 'starter' ? 'insufficient' : 'needs_practice' }, { knowledge_id: 'dfs', label: '深度优先搜索', assessment: scenario === 'starter' ? 'insufficient' : 'needs_practice' }],
      evidence: [{ text: scenario === 'starter' ? '练习样本不足，目前提供通用入门顺序，不判断薄弱点。' : '模拟分析：最近 7 天，图遍历相关练习 4 次，其中 3 次未通过。', sample_count: scenario === 'starter' ? 0 : 4, window_days: 7 }],
      next_step_id: next ? next.step_id : null, next_problem_id: next ? next.problems[0].problem_id : null, steps
    }
  }
  router.get('/learning-path', (req, res) => {
    if (!authorize(res)) return
    const scenario = req.query.mock_path || 'ready'
    setTimeout(() => {
      if (scenario === 'unauthenticated') return res.status(401).json({ error: 'not_authenticated', data: 'Mock session expired' })
      if (scenario === 'expired' && req.query.revision) return res.status(410).json({ error: 'version_expired', data: 'Mock version expired' })
      if (scenario === 'error') return res.status(503).json({ error: 'unavailable', data: 'Mock path load failure' })
      if (['insufficient_data', 'empty', 'generating'].includes(scenario)) {
        return ok(res, { status: scenario, reason_code: scenario === 'empty' ? 'no_eligible_problems' : scenario, message: { insufficient_data: '完成一些题目后，我们会根据练习记录生成路径。', empty: '当前没有适合且可访问的推荐题目，可以先去题库自主练习。', generating: '正在分析已有练习记录，请稍候。' }[scenario], retry_after_seconds: 10 })
      }
      const data = makePath(scenario, req.query.revision === '2' ? 2 : 1)
      if (scenario === 'new_version' && data.revision === 1) data.latest_path = makePath(scenario, 2)
      if (scenario === 'compatibility') {
        data.steps[0].step_id = 1
        data.steps[0].problems.push({ ...data.steps[1].problems[0], problem_id: '2' })
        data.steps[0].status = 'future_status'
        data.focus_points[0].assessment = 'mastered'
        data.focus_points[1].assessment = 'future_assessment'
        data.next_step_id = '1'
        data.next_problem_id = 2
        delete data.evidence
      }
      if (scenario === 'invalid_data') data.next_problem_id = 'missing-problem'
      ok(res, data)
    }, 500)
  })
  router.post('/learning-path/explanation', (req, res) => {
    if (!authorize(res)) return
    const data = makePath(req.body.mock_path, Number(req.body.revision))
    const stepID = req.body.mock_path === 'compatibility' && String(req.body.step_id) === '1' ? 'step-1' : req.body.step_id
    const step = data.steps.find(s => s.step_id === stepID)
    if (req.body.path_id !== 'mock-path' || ![1, 2].includes(data.revision) || !step) return res.status(409).json({ error: 'version_mismatch', data: 'Unknown path version or step' })
    setTimeout(() => {
      if (req.body.mock_path === 'explanation_error') return res.status(503).json({ error: 'unavailable', data: 'Mock explanation failure' })
      ok(res, { path_id: data.path_id, revision: data.revision, step_id: req.body.step_id, status: 'ready', generated_at: new Date().toISOString(), text: '模拟解释（未调用 AI）：' + (req.body.mock_path === 'starter' ? '目前练习数据不足，本步骤属于通用入门训练。' : '根据模拟练习记录，这一步帮助你巩固对应知识点。') + '训练目标是：' + step.objective + '。题目和顺序由规则程序确定，解释不会改变这条路径。' })
    }, 800)
  })
}
