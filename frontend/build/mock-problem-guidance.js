'use strict'

// Proposed API only. In-memory sessions survive browser refresh, not server restart.
// Mount before the shared fallback: require('./mock-problem-guidance')(router, context)
module.exports = function (router, context) {
  const sessions = new Map()
  let sequence = 0
  const id = value => typeof value === 'string' && /^[\w-]{1,128}$/.test(value)
  const scenarios = ['waiting', 'available', 'insufficient', 'pending', 'failure', 'exhausted', 'disabled', 'unknown', 'permission-error', 'contest-allowed']
  const ok = (res, data) => res.json({ error: null, data })
  const fail = (res, status, error) => res.status(status).json({ error, data: null })
  function locate (req, res) {
    if (!context.isLoggedIn()) { fail(res, 401, 'not_authenticated'); return null }
    const problemID = req.query.problem_id
    const contestID = req.query.contest_id == null ? null : req.query.contest_id
    if (!id(problemID) || (contestID !== null && !id(contestID))) { fail(res, 400, 'invalid_context'); return null }
    if (!context.problems.some(problem => String(problem._id) === problemID)) { fail(res, 404, 'problem_not_found'); return null }
    const scenario = req.query.mock_guidance == null ? 'waiting' : req.query.mock_guidance
    if (typeof scenario !== 'string' || !scenarios.includes(scenario)) { fail(res, 400, 'invalid_scenario'); return null }
    if (scenario === 'permission-error') { fail(res, 503, 'capability_unavailable'); return null }
    const key = JSON.stringify([String(context.user.id), problemID, contestID, scenario])
    if (!sessions.has(key)) {
      const allowed = scenario !== 'disabled' && (!contestID || scenario === 'contest-allowed')
      sessions.set(key, {
        user_id: String(context.user.id),
        context: { problem_id: problemID, contest_id: contestID },
        session_id: 'guidance-session-' + (++sequence),
        scenario,
        capabilities: { can_request: allowed, contest_allowed: !!contestID && scenario === 'contest-allowed' },
        status: !allowed ? 'disabled' : scenario === 'unknown' ? 'future_state' : scenario === 'waiting' ? 'waiting' : scenario === 'exhausted' ? 'exhausted' : scenario === 'insufficient' ? 'insufficient' : 'ready',
        stage: 'understand',
        quota: { limit: 3, remaining: scenario === 'exhausted' ? 0 : 3 },
        available_at: scenario === 'waiting' ? new Date(Date.now() + 30000).toISOString() : null,
        messages: [],
        last_request_id: null,
        attempted: new Map(),
        active: null,
        message: !allowed ? (contestID ? '本场比赛未开放解题引导。' : '当前教学配置已关闭本题引导。') : ''
      })
    }
    const state = sessions.get(key)
    if (state.status === 'waiting' && Date.now() >= Date.parse(state.available_at)) state.status = 'ready'
    return state
  }
  function snapshot (state) {
    return {
      user_id: state.user_id,
      context: state.context,
      session_id: state.session_id,
      capabilities: state.capabilities,
      status: state.status,
      stage: state.stage,
      quota: state.quota,
      available_at: state.available_at,
      server_time: new Date().toISOString(),
      messages: state.messages,
      message: state.message,
      last_request_id: state.last_request_id
    }
  }
  router.get('/problem-guidance', (req, res) => {
    const state = locate(req, res)
    if (state) ok(res, snapshot(state))
  })
  router.post('/problem-guidance/messages', async (req, res) => {
    const state = locate(req, res)
    if (!state) return
    if (!state.capabilities.can_request || (state.context.contest_id && !state.capabilities.contest_allowed)) return fail(res, 403, 'permission_denied')
    const body = req.body
    if (!body || typeof body !== 'object' || Array.isArray(body) || !id(body.request_id) ||
        typeof body.text !== 'string' || body.text.length > 1000) return fail(res, 400, 'invalid_input')
    if (body.session_id !== state.session_id) return fail(res, 409, 'session_mismatch')
    const text = body.text.trim()
    const attempt = state.attempted.get(body.request_id)
    if (attempt && attempt.text !== text) return fail(res, 409, 'request_mismatch')
    // Duplicate transport retries are never charged twice, even after quota exhaustion.
    if (attempt && attempt.complete) return ok(res, snapshot(state))
    if (state.active) return ok(res, snapshot(state))
    if (state.quota.remaining <= 0) return fail(res, 429, 'quota_exhausted')
    if (!['ready', 'insufficient', 'failed'].includes(state.status)) return fail(res, 409, 'not_available')
    if (text.length < 12) {
      state.attempted.set(body.request_id, { text, complete: false })
      state.status = 'insufficient'
      return ok(res, snapshot(state))
    }
    // The fixture asks for a concrete input/output detail to resolve insufficient input.
    if (state.scenario === 'insufficient' && !/输入|输出|目标|条件/.test(text)) {
      state.status = 'insufficient'
      return ok(res, snapshot(state))
    }
    if (state.scenario === 'failure' && !state.failureShown) {
      state.attempted.set(body.request_id, { text, complete: false })
      state.status = 'failed'
      state.failureShown = true
      return fail(res, 503, 'generation_failed')
    }
    state.attempted.set(body.request_id, { text, complete: false })
    state.active = body.request_id
    state.status = 'generating'
    if (state.scenario === 'pending') await new Promise(resolve => setTimeout(resolve, 2200))
    const stages = ['understand', 'knowledge', 'direction']
    const index = stages.indexOf(state.stage)
    const guidance = {
      '1001': [
        '先看样例：输入里有几个数，输出与它们有什么关系？如果其中一个数是负数，你的题意描述还成立吗？',
        '这里需要保存多少信息？请回忆输入输出与整数运算，并检查题目给出的数值范围。',
        '试着按“读入、计算、输出”拆成几步，并自己验证负数和边界值。哪一步仍让你不确定？'
      ],
      '1002': [
        '题目要求最少移动次数。请在样例上标出起点、终点和不能进入的位置：走到终点与找到最短路线有何区别？',
        '如果把每个可走格子看成一个状态，一次合法移动能联系哪些状态？你学过哪些逐步探索状态的办法？',
        '如果先探索距离起点一步的位置，再探索两步的位置，会有什么性质？请思考怎样记录访问状态，避免重复探索。'
      ],
      '1003': [
        '请圈出样例中的每个连通区域。上下左右相邻与对角相邻是否都符合题意？',
        '从一个尚未归类的格子出发，怎样找出与它相连的所有格子？这与哪些图遍历知识有关？',
        '一次完整遍历结束后，怎样区分已经归类和还未归类的格子？试着描述下一次遍历从哪里开始。'
      ]
    }
    const fallback = ['你能列出题目的输入、输出和限制，并手动解释一个样例吗？', '你已经发现的限制，与学过的哪些知识或数据结构有关？', '试着把方案拆成几个步骤，并用一个边界例子检查。哪一步还不能说明白？']
    state.messages.push({ id: body.request_id + '-student', role: 'student', stage: state.stage, text },
      { id: body.request_id + '-guide', role: 'guide', stage: state.stage, text: (guidance[state.context.problem_id] || fallback)[index] })
    state.quota.remaining--
    state.stage = stages[Math.min(index + 1, 2)]
    state.status = state.quota.remaining === 0 ? 'exhausted' : 'ready'
    state.last_request_id = body.request_id
    state.attempted.get(body.request_id).complete = true
    state.active = null
    if (!context.isLoggedIn()) return fail(res, 401, 'not_authenticated')
    ok(res, snapshot(state))
  })
}
