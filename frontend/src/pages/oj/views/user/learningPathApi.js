import { contractRequest } from '@/api/agent'

export function validatePath (path) {
  if (!path || typeof path.path_id !== 'string' || path.status !== 'active' || !Array.isArray(path.steps)) throw new Error('活动路径数据不完整。')
  const orders = new Set()
  for (const step of path.steps) {
    if (!step || !Number.isInteger(step.order) || step.order < 1 || orders.has(step.order) || typeof step.knowledge_code !== 'string' ||
      (step.problem_id !== null && typeof step.problem_id !== 'string')) throw new Error('学习步骤数据不完整。')
    orders.add(step.order)
  }
  return path
}
export const getCurrentPath = () => contractRequest('get', 'recommendation/path').then(validatePath)
export const refreshPath = key => contractRequest('post', 'recommendation/refresh', {}, { 'Idempotency-Key': key }).then(validatePath)
