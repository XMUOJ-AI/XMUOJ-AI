// Proposed frontend contract. Capabilities and all session limits are server-owned.
export const stages = [
  { id: 'understand', label: '理解题意', prompt: '请用自己的话描述输入、目标，以及你目前卡在哪里。' },
  { id: 'knowledge', label: '识别知识点', prompt: '结合上一条追问，你发现了哪些条件？它们与学过的什么知识有关？' },
  { id: 'direction', label: '提示算法方向', prompt: '你打算怎样组织求解步骤？说说你的想法或仍不确定的地方。' }
]
const statuses = ['waiting', 'ready', 'insufficient', 'generating', 'failed', 'exhausted', 'disabled']
export function id (value) {
  if (typeof value === 'number' && Number.isSafeInteger(value) && value > 0) return String(value)
  return typeof value === 'string' && /^[\w-]{1,128}$/.test(value) ? value : null
}
function object (value) { return value && typeof value === 'object' && !Array.isArray(value) }
function invalid () { throw Object.assign(new Error('Invalid guidance data'), { code: 'invalid_data' }) }
export function normalizeGuidance (raw, expected) {
  if (!object(raw) || !object(raw.context) || !object(raw.capabilities) || !object(raw.quota)) invalid()
  if (!id(raw.user_id) || id(raw.user_id) !== expected.user_id || !id(raw.context.problem_id) ||
      id(raw.context.problem_id) !== expected.problem_id ||
      (raw.context.contest_id !== null && !id(raw.context.contest_id)) ||
      id(raw.context.contest_id) !== expected.contest_id || !id(raw.session_id)) invalid()
  if (expected.session_id && id(raw.session_id) !== expected.session_id) invalid()
  const stage = stages.findIndex(item => item.id === raw.stage)
  if (stage < 0 || !Array.isArray(raw.messages)) invalid()
  const seen = new Set()
  const messages = raw.messages.map(message => {
    if (!object(message) || !id(message.id) || seen.has(id(message.id)) ||
        !['student', 'guide'].includes(message.role) || !stages.some(item => item.id === message.stage) ||
        typeof message.text !== 'string' || !message.text.trim() || message.text.length > 4000) invalid()
    seen.add(id(message.id))
    return { id: id(message.id), role: message.role, text: message.text, stage: message.stage }
  })
  const { limit, remaining } = raw.quota
  if (!Number.isSafeInteger(limit) || !Number.isSafeInteger(remaining) || remaining < 0 || limit < remaining) invalid()
  const now = typeof raw.server_time === 'string' ? Date.parse(raw.server_time) : NaN
  const available = raw.available_at === null ? null : (typeof raw.available_at === 'string' ? Date.parse(raw.available_at) : NaN)
  if (!Number.isFinite(now) || (available !== null && !Number.isFinite(available)) || (raw.status === 'waiting' && available === null)) invalid()
  const status = statuses.includes(raw.status) ? raw.status : 'unknown'
  return {
    session_id: id(raw.session_id),
    status,
    stage,
    messages,
    quota: { limit, remaining },
    server_time: now,
    available_at: available,
    allowed: status !== 'unknown' && raw.capabilities.can_request === true &&
      (!expected.contest_id || raw.capabilities.contest_allowed === true),
    message: typeof raw.message === 'string' ? raw.message : ''
  }
}
export function errorMessage (error) {
  const status = error.response && error.response.status
  if (status === 401 || error.code === 'not_authenticated') return '登录状态已失效，请登录后重新检查。'
  if (status === 403 || error.code === 'permission_denied') return '当前未获准使用解题引导。'
  if (error.code === 'invalid_data') return '引导数据暂不完整，暂时无法确认可用状态。'
  return '暂时无法获取引导，请稍后重试。'
}
