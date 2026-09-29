export const categories = [
  ['basic', '基础'], ['data_structure', '数据结构'], ['algorithm', '算法'],
  ['paradigm', '算法范式'], ['mathematics', '数学'], ['string', '字符串'], ['graph', '图论']
]

export function categoryLabel (value) {
  return (categories.find(item => item[0] === value) || [null, value])[1] || '—'
}

export function positiveInt (value, fallback, maximum) {
  const number = Number(value)
  return Number.isInteger(number) && number >= 1 && number <= maximum ? number : fallback
}

export function errorMessage (error) {
  if (error && error.status === 401) return '登录已失效，请重新登录。'
  if (error && error.status === 404) return '知识点不存在或暂不可见。'
  return '加载失败，请稍后重试。'
}
