// Proposed contract: identity and judge revision are echoed by every successful response.
export const ANALYSIS_VERSION = 'submission-analysis-v1'
export const isObject = value => value !== null && typeof value === 'object' && !Array.isArray(value)
export const validId = value => (typeof value === 'string' && /^[\w-]{1,128}$/.test(value)) || (Number.isSafeInteger(value) && value > 0)
export const sameId = (a, b) => validId(a) && validId(b) && String(a) === String(b)
export const supportedResult = value => [0, -1, 1, 2, 4].indexOf(value) !== -1

export const messages = {
  idle: '点击后才会生成解读，不会修改或代提交代码。',
  checking: '正在检查当前提交的解读权限…',
  generating: '正在生成解读，请稍候…',
  login_required: '登录已过期或尚未登录，请登录后重新检查。',
  forbidden: '当前提交不允许解读。公开可见的代码不代表可以使用 AI 解读。比赛与实验策略由服务端决定。',
  busy: '服务繁忙，请稍后重试。',
  quota_exceeded: '解读额度已用完，请稍后重新检查。',
  insufficient_evidence: '当前依据不足，暂不能给出可靠解读。请结合题面与现有判题信息自行排查。',
  unavailable: '当前状态暂不可解读，请以原判题结果为准。',
  failed: '解读请求失败，原判题结果与代码仍可查看。',
  invalid_response: '返回数据不完整或与当前提交不一致，请重新检查。',
  compile_error: '编译错误请先查看上方编译器信息，修复后重新提交。',
  pending: '提交尚未完成判题，暂不可解读。'
}

export function localState (submission, userId) {
  if (!validId(userId)) return 'login_required'
  if (!isObject(submission) || !validId(submission.id)) return 'unavailable'
  if (!sameId(submission.user_id, userId)) return 'forbidden'
  if (submission.result === -2) return 'compile_error'
  if ([6, 7, 9].indexOf(submission.result) !== -1) return 'pending'
  return supportedResult(submission.result) ? 'idle' : 'unavailable'
}

function identityMatches (data, expected) {
  return isObject(data) && sameId(data.submission_id, expected.submission_id) &&
    sameId(data.user_id, expected.user_id) && data.judge_result === expected.judge_result &&
    data.analysis_version === ANALYSIS_VERSION && typeof data.judge_revision === 'string' &&
    data.judge_revision.length > 0 && data.judge_revision.length <= 200 &&
    (!expected.judge_revision || data.judge_revision === expected.judge_revision)
}

export function normalizeCapability (data, expected) {
  if (!identityMatches(data, expected)) throw new Error('invalid_response')
  if (data.capability !== 'allowed') {
    return {state: data.capability === 'denied' ? 'forbidden' : 'unavailable'}
  }
  return {state: 'idle', revision: data.judge_revision}
}

const safeText = value => typeof value === 'string' && value.trim().length > 0 && value.length <= 4000
export function normalizeAnalysis (data, expected) {
  if (!identityMatches(data, expected) || data.capability !== 'allowed') throw new Error('invalid_response')
  if (data.status !== 'ready') return {state: ['busy', 'insufficient_evidence', 'quota_exceeded'].indexOf(data.status) !== -1 ? data.status : 'unavailable'}
  const scope = data.scope
  if (!isObject(scope) || !Number.isSafeInteger(scope.total_lines) || scope.total_lines < 1 ||
      !Number.isSafeInteger(scope.start_line) || !Number.isSafeInteger(scope.end_line) ||
      scope.start_line < 1 || scope.end_line < scope.start_line || scope.end_line > scope.total_lines ||
      typeof scope.truncated !== 'boolean' || scope.truncated !== (scope.start_line !== 1 || scope.end_line !== scope.total_lines)) throw new Error('invalid_response')
  if (!safeText(data.summary) || !Array.isArray(data.sections) || !data.sections.length || data.sections.length > 8 ||
      !data.sections.every(s => isObject(s) && safeText(s.title) && safeText(s.body) && safeText(s.evidence))) throw new Error('invalid_response')
  return {state: 'ready', result: {summary: data.summary, scope, sections: data.sections.map(s => ({title: s.title, body: s.body, evidence: s.evidence}))}}
}

export function errorState (error) {
  const status = error && error.response && error.response.status
  if (status === 401) return 'login_required'
  if (status === 403) return 'forbidden'
  if (status === 429) return error.code === 'quota_exceeded' ? 'quota_exceeded' : 'busy'
  if (status === 503) return 'busy'
  return error && Object.prototype.hasOwnProperty.call(messages, error.code || error.message) ? (error.code || error.message) : 'failed'
}

// Invalidate synchronously on every context change, including pending Vue watcher updates.
export function createRequestGuard () {
  let sequence = 0
  return {
    next: () => ++sequence,
    invalidate: () => { sequence++ },
    current: (ticket, originalKey, currentKey) => ticket === sequence && originalKey === currentKey
  }
}
