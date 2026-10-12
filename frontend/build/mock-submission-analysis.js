'use strict'

// Proposed contract only. Mount before mock-api's fallback; never connects to a backend/LLM.
// require('./mock-submission-analysis')(router, {user, isLoggedIn: () => loggedIn, problems, submissions})
const crypto = require('crypto')
const VERSION = 'submission-analysis-v1'
const supported = result => [0, -1, 1, 2, 4].indexOf(result) !== -1
const object = value => value !== null && typeof value === 'object' && !Array.isArray(value)
const id = value => (typeof value === 'string' && /^[\w-]{1,128}$/.test(value)) || (Number.isSafeInteger(value) && value > 0)
const match = (a, b) => id(a) && id(b) && String(a) === String(b)
const revision = s => crypto.createHash('sha256').update(JSON.stringify([s.code, s.result, s.statistic_info, s.info])).digest('hex')

module.exports = function (router, context) {
  const {user, isLoggedIn, problems, submissions} = context
  const fixtureCodes = {
    'mock-ac': '#include <iostream>\nint main() {\n  long long a, b;\n  std::cin >> a >> b;\n  std::cout << a + b;\n}',
    'mock-wa': '#include <iostream>\nint main() {\n  int a, b;\n  std::cin >> a >> b;\n  std::cout << a - b;\n}',
    'mock-tle': '#include <iostream>\nint main() {\n  int n, i = 0;\n  std::cin >> n;\n  while (i < n) { std::cout << i; }\n}',
    'mock-re': '#include <iostream>\nint main() {\n  int a, b;\n  std::cin >> a >> b;\n  std::cout << a / b;\n}',
    'mock-ce': '#include <iostream>\nint main() {\n  std::cout << "hello"\n}',
    'mock-pending': 'int main() { return 0; }',
    'mock-other': 'int main() { return 0; }'
  }
  const results = {'mock-ac': 0, 'mock-wa': -1, 'mock-tle': 1, 'mock-re': 4, 'mock-ce': -2, 'mock-pending': 6, 'mock-other': 0}
  if (Array.isArray(submissions) && Array.isArray(problems) && problems[0]) {
    Object.keys(fixtureCodes).forEach(key => {
      if (submissions.some(s => s.id === key)) return
      submissions.push({
        id: key,
        problem: problems[0].id,
        problem_id: problems[0]._id,
        problem_title: problems[0].title,
        user_id: key === 'mock-other' ? 'other-student' : user.id,
        username: key === 'mock-other' ? 'other_student' : user.username,
        language: 'C++',
        code: fixtureCodes[key],
        result: results[key],
        create_time: '2026-09-18T09:00:00Z',
        shared: key === 'mock-other',
        can_unshare: key !== 'mock-other',
        code_length: fixtureCodes[key].length,
        statistic_info: {time_cost: key === 'mock-tle' ? 1000 : 8, memory_cost: 1048576, err_info: key === 'mock-ce' ? 'main.cpp:4:1: error: expected ; before } token (模拟编译信息)' : ''},
        info: {data: []}
      })
    })
  }
  const fail = (res, status, code) => res.status(status).json({error: code, data: null})
  function handle (req, res, generate) {
    if (!isLoggedIn()) return fail(res, 401, 'login_required')
    const input = generate ? req.body : req.query
    if (!object(input) || !id(input.submission_id)) return fail(res, 400, 'invalid_response')
    const submission = submissions.find(s => match(s.id, input.submission_id))
    if (!submission) return fail(res, 404, 'unavailable')
    if (!match(submission.user_id, user.id)) return fail(res, 403, 'forbidden')
    const scenario = typeof req.query.mock_analysis === 'string' ? req.query.mock_analysis : ''
    if (scenario === 'expired') return fail(res, 401, 'login_required')
    const identity = {submission_id: submission.id, user_id: user.id, judge_result: submission.result, judge_revision: revision(submission), analysis_version: VERSION}
    const allowed = supported(submission.result) && scenario !== 'forbidden'
    const base = Object.assign({}, identity, {capability: allowed ? 'allowed' : 'denied'})
    const ok = data => res.json({error: null, data})
    if (!generate) return ok(scenario === 'unknown-capability' ? Object.assign(base, {capability: 'future'}) : base)
    if (!allowed || scenario === 'unknown-capability') return fail(res, 403, 'forbidden')
    if (!match(input.user_id, user.id) || input.judge_result !== submission.result || input.judge_revision !== identity.judge_revision || input.analysis_version !== VERSION) return fail(res, 409, 'invalid_response')
    if (scenario === 'busy') return fail(res, 503, 'busy')
    if (scenario === 'quota') return fail(res, 429, 'quota_exceeded')
    if (scenario === 'failed') return fail(res, 500, 'failed')
    if (scenario === 'insufficient' || fixtureCodes[submission.id] !== submission.code || submission.id === 'mock-001') return ok(Object.assign(base, {status: 'insufficient_evidence'}))
    if (scenario === 'unknown') return ok(Object.assign(base, {status: 'future_state'}))
    const sections = {
      'mock-ac': [
        ['思路', '依次读入两个整数，将两者相加后输出。', '第 3–5 行的输入、加法和输出；题面要求输出两数之和。'],
        ['复杂度', '在固定宽度整数运算假设下，时间 O(1)，额外空间 O(1)。', '仅有两个标量变量与一次加法，没有随输入规模增长的循环。'],
        ['可改进之处', '可核对题面数值范围与 long long 的表示范围，并检查输入失败时的处理。AC 只表示通过现有测试，不能据此推断已掌握。', '第 3 行使用 long long；本示例未提供完整数值约束。']
      ],
      'mock-wa': [
        ['先核对运算含义', '题面要求相加，但输出表达式为相减。建议手算公开样例 1 2，比较期望值 3 与表达式所得 -1。', '第 5 行为 a - b；依据仅为题面、代码和公开样例，未读取隐藏测试点。'],
        ['排查范围', '该差异可能解释 WA，请自行核对题意、边界值与输出格式；尚不能排除其他问题。', '现有判题结果为 WA，没有失败测试输入。']
      ],
      'mock-tle': [
        ['检查循环能否结束', '当 n > 0 时，i 始终为 0，循环条件一直成立并持续输出。建议逐步跟踪变量变化。', '第 3 行 i 初始化为 0；第 5 行循环体没有更新 i。'],
        ['区分耗时来源', '这可能导致超时，先验证循环终止性，再评估输出次数；没有隐藏输入，无法确认所有触发条件。', '判题结果为 TLE；代码有重复输出。']
      ],
      'mock-re': [
        ['核对除法的输入条件', 'b 为 0 时整数除法可能触发运行时错误。建议用本地小输入检查分母条件，并核对题意是否允许除法。', '第 5 行 a / b 没有分母检查；题面要求求和。'],
        ['避免直接归因', '除零是排查方向，不是已经确认的 RE 根因；还需结合可见运行日志定位。', '只有 RE 状态，没有信号、堆栈或失败输入。']
      ]
    }
    const lines = submission.code.split('\n').length
    const truncated = scenario === 'truncated'
    let result = Object.assign({}, base, {
      status: 'ready',
      summary: truncated ? '仅看到了代码开头，以下不涉及未提供的后续逻辑。' : '以下是固定模拟解读，请自行验证每条建议。',
      scope: {start_line: 1, end_line: truncated ? 3 : lines, total_lines: lines, truncated},
      sections: truncated
        ? [{title: '已观察到的内容', body: '仅能确认入口与变量声明，无法判断输入、输出、循环行为或整体复杂度。', evidence: '仅提供第 1–3 行；剩余代码未纳入分析。'}]
        : (sections[submission.id] || []).map(s => ({title: s[0], body: s[1], evidence: s[2]}))
    })
    if (scenario === 'mismatch') result.user_id = 'other-student'
    if (scenario === 'malformed') result.sections = {}
    if (scenario === 'version') result.analysis_version = 'future-v2'
    if (scenario === 'slow') {
      return setTimeout(() => {
        if (!isLoggedIn()) return fail(res, 401, 'login_required')
        if (!match(submission.user_id, user.id)) return fail(res, 403, 'forbidden')
        if (revision(submission) !== identity.judge_revision) return fail(res, 409, 'invalid_response')
        ok(result)
      }, 2000)
    }
    return ok(result)
  }
  router.get('/submission-analysis', (req, res) => handle(req, res, false))
  router.post('/submission-analysis/generate', (req, res) => handle(req, res, true))
}
