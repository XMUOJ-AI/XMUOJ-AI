// Keep backend adaptation local to this feature; do not infer recommendation results.
export function id (value) {
  if (typeof value === 'string' && value.trim()) return value.trim()
  return typeof value === 'number' && Number.isFinite(value) ? String(value) : null
}

function text (value, fallback = '') { return typeof value === 'string' ? value : fallback }
function list (value) { return Array.isArray(value) ? value : [] }
function invalid () { throw Object.assign(new Error('Invalid learning path'), { code: 'invalid_data' }) }

export function normalizePath (raw) {
  if (!raw || typeof raw !== 'object' || typeof raw.status !== 'string') invalid()
  if (raw.status !== 'ready') return { status: raw.status, message: text(raw.message), retry_after_seconds: raw.retry_after_seconds }
  const pathId = id(raw.path_id)
  const revision = id(raw.revision)
  if (!pathId || !revision || !Array.isArray(raw.steps) || !raw.steps.length) invalid()
  const stepIds = new Set()
  const steps = raw.steps.map((step, index) => {
    if (!step || !id(step.step_id) || stepIds.has(id(step.step_id))) invalid()
    stepIds.add(id(step.step_id))
    if (step.problems != null && !Array.isArray(step.problems)) invalid()
    const problemIds = new Set()
    const problems = list(step.problems).map(problem => {
      if (!problem || !id(problem.problem_id) || !id(problem.display_id) || problemIds.has(id(problem.problem_id))) invalid()
      problemIds.add(id(problem.problem_id))
      const context = problem.context || {}
      const supported = context.type === 'public' || (context.type === 'contest' && id(context.contest_id))
      return {
        ...problem,
        problem_id: id(problem.problem_id),
        display_id: id(problem.display_id),
        title: text(problem.title, '未命名题目'),
        status: text(problem.status),
        context: { type: context.type, contest_id: id(context.contest_id) },
        availability: supported && problem.availability === 'available' ? 'available' : 'unavailable',
        unavailable_reason: text(problem.unavailable_reason, supported ? '题目暂不可用' : '题目入口暂不支持')
      }
    })
    return {
      ...step,
      step_id: id(step.step_id),
      order: Number.isFinite(step.order) ? step.order : index + 1,
      title: text(step.title, '训练步骤'),
      objective: text(step.objective, '训练目标暂未提供'),
      status: text(step.status),
      explanation_available: step.explanation_available === true,
      problems
    }
  })
  const nextStep = id(raw.next_step_id)
  const nextProblem = id(raw.next_problem_id)
  if (nextStep || nextProblem) {
    const step = steps.find(item => item.step_id === nextStep)
    if (!step || !step.problems.some(problem => problem.problem_id === nextProblem && problem.availability === 'available')) invalid()
  }
  return {
    ...raw,
    path_id: pathId,
    revision,
    summary: text(raw.summary, '你的练习路径'),
    focus_points: list(raw.focus_points).filter(point => point && typeof point.label === 'string'),
    evidence: list(raw.evidence).filter(item => item && typeof item.text === 'string'),
    steps,
    next_step_id: nextStep,
    next_problem_id: nextProblem
  }
}

export function statusLabel (status) {
  const labels = { completed: '已完成', judging: '判题中', pending: '未完成', skipped: '已跳过' }
  return Object.prototype.hasOwnProperty.call(labels, status) ? labels[status] : '状态待确认'
}

export function assessmentLabel (status) {
  const labels = { insufficient: '待了解', needs_practice: '建议巩固', mastered: '已掌握' }
  return Object.prototype.hasOwnProperty.call(labels, status) ? labels[status] : '评估待确认'
}

export function errorFeedback (error) {
  const response = error.response || {}
  const body = response.data || {}
  const code = error.code || body.error
  const status = response.status || error.status
  if (status === 401 || code === 'not_authenticated') return { message: '登录已过期，请重新登录。', action: 'login', label: '重新登录' }
  if ([409, 410].includes(status) || ['version_mismatch', 'version_expired'].includes(code)) return { message: '这条路径的版本已失效，请查看最新路径。', action: 'latest', label: '查看最新路径' }
  if (status === 403 || code === 'permission_denied') return { message: '当前无权访问学习路径。', action: null }
  if (status === 429 || status === 503 || code === 'busy') return { message: '服务暂时繁忙，请稍后重试。', action: 'retry', label: '重试' }
  if (code === 'invalid_data') return { message: '路径数据暂不完整，请稍后重试。', action: 'retry', label: '重试' }
  return { message: '请求失败，请检查网络或稍后重试。', action: 'retry', label: '重试' }
}
