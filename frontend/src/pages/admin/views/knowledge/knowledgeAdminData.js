export const categories = [
  ['basic', '基础'], ['data_structure', '数据结构'], ['algorithm', '算法'],
  ['paradigm', '算法范式'], ['mathematics', '数学'], ['string', '字符串'], ['graph', '图论']
]

export const statusOptions = [['draft', '草稿'], ['active', '生效'], ['deprecated', '已废弃']]

export function labelOf (options, value) {
  const option = options.find(item => item[0] === value)
  return option ? option[1] : value || '—'
}

export function statusType (status) {
  return status === 'active' ? 'success' : status === 'deprecated' ? 'info' : 'warning'
}

export function errorText (error) {
  const messages = {
    KNOWLEDGE_AUTH_REQUIRED: '登录已失效，请重新登录。',
    KNOWLEDGE_PERMISSION_DENIED: '当前账号没有此功能权限。',
    KNOWLEDGE_NOT_FOUND: '对象不存在或不在权限范围内。',
    KNOWLEDGE_INPUT_INVALID: '输入内容不符合要求，请检查后重试。',
    KNOWLEDGE_CODE_CONFLICT: '知识点编码已经存在。',
    KNOWLEDGE_NAME_CONFLICT: '知识点名称与现有数据冲突。',
    KNOWLEDGE_VERSION_CONFLICT: '数据已被其他人更新，请刷新后重试。',
    KNOWLEDGE_STATE_CONFLICT: '当前状态或引用关系不允许执行此操作。',
    KNOWLEDGE_DEPENDENCY_EXISTS: '该依赖关系已经存在或正在审核。',
    KNOWLEDGE_DEPENDENCY_CYCLE: '该操作会形成依赖环，无法提交。',
    KNOWLEDGE_SELF_DEPENDENCY: '知识点不能依赖自身。',
    KNOWLEDGE_MAPPING_INVALID: '映射必须包含且只能包含一个主知识点。',
    KNOWLEDGE_REVIEW_CONFLICT: '该对象已有待审核申请或已经被处理。',
    KNOWLEDGE_SELF_REVIEW_FORBIDDEN: '提交人不能审核自己的申请。'
  }
  return messages[error && error.code] || '操作失败，请稍后重试。'
}

export function compactParams (values) {
  return Object.fromEntries(Object.entries(values).filter(([, value]) => value !== '' && value !== null && value !== undefined))
}

export function localDateTime (value) {
  if (!value) return '—'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('zh-CN', { hour12: false })
}

