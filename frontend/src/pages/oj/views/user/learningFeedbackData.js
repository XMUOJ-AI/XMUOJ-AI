// Proposed API adaptation. Never infer capability or mastery from an unknown value.
export const object = value => value !== null && typeof value === 'object' && !Array.isArray(value)
export const id = value => (typeof value === 'string' && /^[a-zA-Z0-9_-]{1,100}$/.test(value)) || (typeof value === 'number' && Number.isSafeInteger(value) && value > 0) ? String(value) : null
const text = value => typeof value === 'string' ? value : ''
const invalid = () => { throw Object.assign(new Error('Invalid feedback data'), { code: 'invalid_data' }) }
const list = value => { if (!Array.isArray(value)) invalid(); return value }
const date = value => typeof value === 'string' && /^\d{4}-\d{2}-\d{2}T/.test(value) && Number.isFinite(Date.parse(value)) ? value : null

function identity (raw, userId) {
  if (!object(raw) || !id(userId) || id(raw.user_id) !== id(userId)) invalid()
}
function unique (items, key) {
  const seen = new Set()
  items.forEach(item => {
    if (!object(item) || !id(item[key]) || seen.has(id(item[key]))) invalid()
    seen.add(id(item[key]))
  })
  return items
}
export function normalizeSummary (raw, userId) {
  identity(raw, userId)
  const status = ['ready', 'empty', 'disabled'].includes(raw.status) ? raw.status : 'unknown'
  const ready = status === 'ready'
  const range = object(raw.range) ? raw.range : {}
  const start = date(range.start)
  const end = date(range.end)
  if (ready && (!start || !end || Date.parse(start) > Date.parse(end))) invalid()
  const evidence = ready ? unique(list(raw.evidence), 'id').map(item => {
    if (!text(item.text) || !date(item.occurred_at)) invalid()
    return { id: id(item.id), text: item.text, occurred_at: item.occurred_at }
  }) : []
  if (ready && (!Number.isSafeInteger(raw.submission_count) || raw.submission_count < 1 || !evidence.length)) invalid()
  return {
    status,
    range: { start, end },
    evidence,
    submission_count: ready ? raw.submission_count : 0,
    can_generate: ready && object(raw.capabilities) && raw.capabilities.can_generate === true,
    reason: text(raw.reason)
  }
}
export function normalizeFeedback (raw, userId, generationId) {
  identity(raw, userId)
  if (!id(raw.generation_id) || (generationId && id(raw.generation_id) !== id(generationId))) invalid()
  const status = ['generating', 'ready', 'insufficient', 'failed', 'disabled'].includes(raw.status) ? raw.status : 'unknown'
  const base = { generation_id: id(raw.generation_id), status, message: text(raw.message), overview: '', points: [], suggestions: [], sources: [] }
  if (status !== 'ready') return base
  if (!text(raw.overview)) invalid()
  const sources = unique(list(raw.sources), 'id').map(source => ({
    id: id(source.id),
    title: text(source.title) || '资料',
    version: text(source.version),
    available: source.availability === 'available' && !!text(source.excerpt),
    excerpt: source.availability === 'available' ? text(source.excerpt) : '',
    reason: text(source.reason) || '资料暂不可用，无法核对引用内容。'
  }))
  // Missing references remain visible as unavailable; never fabricate a URL.
  const references = rawIds => list(rawIds).map(value => {
    const key = id(value)
    if (!key) invalid()
    if (!sources.some(source => source.id === key)) sources.push({ id: key, title: '引用资料', version: '', available: false, excerpt: '', reason: '此引用未返回可核对的资料。' })
    return key
  })
  const points = unique(list(raw.points), 'id').map(point => {
    if (!text(point.label) || !text(point.observation)) invalid()
    return { id: id(point.id), label: point.label, assessment: text(point.assessment), observation: point.observation, source_ids: references(point.source_ids) }
  })
  const suggestions = unique(list(raw.suggestions), 'id').map(item => {
    if (!text(item.action)) invalid()
    return { id: id(item.id), action: item.action, source_ids: references(item.source_ids) }
  })
  if (!points.length || !suggestions.length) invalid()
  const basis = normalizeSummary(raw.basis, userId)
  if (basis.status !== 'ready') invalid()
  return { ...base, basis, overview: raw.overview, points, suggestions, sources }
}
export function assessmentLabel (status) {
  switch (status) {
    case 'observed': return '已有练习记录'
    case 'review': return '建议复习'
    case 'insufficient': return '依据不足'
    default: return '评估待确认'
  }
}
export function errorFeedback (error) {
  const status = error.response && error.response.status
  const code = error.code || (error.response && error.response.data && error.response.data.error)
  if (status === 401 || code === 'not_authenticated') return { message: '登录已过期，请登录后重新加载学习反馈。', action: 'login' }
  if (status === 403 || code === 'permission_denied') return { message: '当前账号暂不可使用学习反馈。', action: null }
  if (status === 429 || status === 503 || code === 'busy') return { message: '学习反馈服务繁忙，请稍后重试。', action: 'retry' }
  if (code === 'invalid_data') return { message: '反馈数据暂不可用，请重新加载后再试。', action: 'reload' }
  return { message: '暂时无法获取学习反馈，请重试。', action: 'retry' }
}
