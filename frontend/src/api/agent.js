import axios from 'axios'

const client = axios.create({ baseURL: '/api', timeout: 15000, xsrfHeaderName: 'X-CSRFToken', xsrfCookieName: 'csrftoken' })
export const runOptions = { language: 'zh-CN', detail_level: 'normal' }
export function requestKey () {
  // getRandomValues also works on installations served over plain HTTP.
  const key = typeof crypto.randomUUID === 'function' ? crypto.randomUUID()
    : Array.from(crypto.getRandomValues(new Uint32Array(4)), value => value.toString(16).padStart(8, '0')).join('')
  return 'web-' + key
}
export function apiError (error) {
  const body = error.response && error.response.data
  return Object.assign(error, { code: (body && body.error) || error.code, status: error.response ? error.response.status : error.status,
    message: (body && body.data && body.data.message) || error.message || '请求失败，请稍后重试。' })
}
export function errorText (error) {
  if (error.status === 401) return '登录已失效，请重新登录后重试。'
  if (error.status === 403) return '当前账号没有使用此功能的权限。'
  if (error.code === 'AGENT_POLL_PAUSED') return '生成仍在进行，已暂停自动检查。点击“继续查看”获取同一次生成的结果。'
  if (error.code === 'AGENT_INVALID_RESPONSE') return '服务返回的数据不完整，请稍后重试。'
  return error.message || '请求失败，请稍后重试。'
}
export async function contractRequest (method, url, data, headers) {
  try {
    const response = await client({ method, url, data, headers })
    if (!response.data || response.data.error !== null || response.data.data == null) {
      throw Object.assign(new Error('服务返回的数据不完整。'), { response, code: 'AGENT_INVALID_RESPONSE' })
    }
    return response.data.data
  } catch (error) { throw apiError(error) }
}
export const startConversation = problemId => contractRequest('post', 'agent/v1/conversations', { problem_id: String(problemId), service_type: 'socratic_hint' })
const invalid = () => { throw Object.assign(new Error('服务返回的数据不完整。'), { code: 'AGENT_INVALID_RESPONSE' }) }
const text = value => typeof value === 'string' && value.trim().length > 0
const texts = value => Array.isArray(value) && value.every(text)
export function validateResult (service, result, request) {
  if (!result || result.contains_full_solution !== false) invalid()
  if (service === 'code_explanation') {
    if (!text(result.summary) || !Array.isArray(result.sections) || !result.sections.length ||
      !result.sections.every(x => x && text(x.title) && text(x.explanation) && texts(x.code_refs)) ||
      !result.complexity || !text(result.complexity.time) || !text(result.complexity.space) ||
      !texts(result.complexity.assumptions) || !texts(result.improvement_directions)) invalid()
  } else if (service === 'socratic_hint') {
    if (!text(result.question) || !text(result.focus) || !Number.isInteger(result.hint_level) || result.hint_level < 1 || result.hint_level > 3) invalid()
  } else if (service === 'learning_path_explanation') {
    if (result.path_id !== request.path_id || !text(result.overview) || !text(result.next_action) || !Array.isArray(result.steps) ||
      !result.steps.length || !result.steps.every(x => x && Number.isInteger(x.order) && x.order > 0 && text(x.knowledge_code) && text(x.reason))) invalid()
  } else invalid()
  return result
}

// Retain attempt.key after an uncertain POST and attempt.runId after a polling
// failure. Retrying observes the same generation instead of charging a new run.
export async function runAgent (request, attempt, { current = () => true, progress = () => {}, maxPolls = 30, wait = () => new Promise(resolve => setTimeout(resolve, 1500)) } = {}) {
  const check = () => { if (!current()) throw Object.assign(new Error('请求上下文已变化'), { code: 'AGENT_CANCELLED' }) }
  check()
  if (!attempt.key) attempt.key = requestKey()
  let run = attempt.runId
    ? await contractRequest('get', 'agent/v1/runs/' + encodeURIComponent(attempt.runId))
    : await contractRequest('post', 'agent/v1/runs', { ...request, options: runOptions }, { 'Idempotency-Key': attempt.key })
  for (let count = 0; ; count++) {
    check()
    if (!run || !text(run.run_id) || run.service_type !== request.service_type || (attempt.runId && attempt.runId !== run.run_id)) invalid()
    attempt.runId = run.run_id
    progress(run.status)
    if (run.status === 'succeeded') { validateResult(request.service_type, run.result, request); return run }
    if (['failed', 'blocked', 'cancelled'].includes(run.status)) {
      const detail = run.error_detail || {}
      throw Object.assign(new Error(detail.message || '本次生成未完成，请稍后重试。'), { code: detail.code, terminal: true })
    }
    if (!['queued', 'running'].includes(run.status)) invalid()
    if (count >= maxPolls) throw Object.assign(new Error('自动检查已暂停。'), { code: 'AGENT_POLL_PAUSED' })
    await wait()
    check()
    run = await contractRequest('get', 'agent/v1/runs/' + encodeURIComponent(attempt.runId))
  }
}
