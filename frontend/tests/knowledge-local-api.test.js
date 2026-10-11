import { beforeEach, describe, expect, test, vi } from 'vitest'

const { get, adminClient, dispatch } = vi.hoisted(() => ({ get: vi.fn(), adminClient: vi.fn(), dispatch: vi.fn() }))
vi.mock('axios', () => ({ default: { get, create: () => adminClient } }))
vi.mock('@/store', () => ({ default: { dispatch } }))

import { getKnowledgeCollection, loadKnowledgeDetail } from '../src/pages/oj/views/knowledge/knowledgeApi'
import { getKnowledgePointCollection, listKnowledgeReviews, reviewKnowledge, submitProblemKnowledgeMappings } from '../src/pages/admin/views/knowledge/knowledgeAdminApi'

const response = (data, status = 200) => ({ status, data: { error: null, data, request_id: 'req_test' } })
const failure = (code, status) => ({ response: { status, data: { error: code, data: { message: code }, request_id: 'req_failed' } } })

beforeEach(() => { get.mockReset(); adminClient.mockReset(); dispatch.mockReset() })

describe('local knowledge contract', () => {
  test('keeps complete small detail arrays without extra requests', async () => {
    const point = { code: 'root', prerequisites: [{ code: 'parent' }], dependents: [], related_problems: [] }
    get.mockResolvedValue(response(point))
    const detail = await loadKnowledgeDetail('root')
    expect(detail.point).toBe(point)
    expect(detail.collections.prerequisites).toMatchObject({ items: point.prerequisites, total: 1, page: 1 })
    expect(get).toHaveBeenCalledTimes(1)
  })

  test('uses bounded collection endpoints when local detail exceeds 100 rows', async () => {
    get.mockImplementation(async (url, options) => {
      if (url === 'knowledge-points/root' && !options.params) throw failure('KNOWLEDGE_PAGINATION_REQUIRED', 409)
      if (url === 'knowledge-points/root') return response({ code: 'root', prerequisites: [], dependents: [], related_problems: [] })
      return response({ items: [{ code: options.params.direction || 'problem' }], total: 121, page: 1, page_size: 20 })
    })
    const detail = await loadKnowledgeDetail('root')
    expect(detail.collections.prerequisites.total).toBe(121)
    expect(detail.collections.related_problems.items).toEqual([{ code: 'problem' }])
    expect(get).toHaveBeenCalledTimes(5)
    expect(get).toHaveBeenCalledWith('knowledge-points/root', expect.objectContaining({ params: { include_collections: false } }))
    expect(get).toHaveBeenCalledWith('knowledge-points/root/dependencies', expect.objectContaining({ params: { direction: 'dependents', page: 1, page_size: 20 } }))
    expect(get).toHaveBeenCalledWith('knowledge-points/root/related-problems', expect.objectContaining({ params: { page: 1, page_size: 20 } }))
    await getKnowledgeCollection('root', 'related_problems', 7)
    expect(get).toHaveBeenLastCalledWith('knowledge-points/root/related-problems', expect.objectContaining({ params: { page: 7, page_size: 20 } }))
  })

  test('does not mistake authentication or other conflicts for pagination', async () => {
    get.mockRejectedValue(failure('KNOWLEDGE_AUTH_REQUIRED', 401))
    await expect(loadKnowledgeDetail('root')).rejects.toMatchObject({ code: 'KNOWLEDGE_AUTH_REQUIRED', status: 401, requestId: 'req_failed' })
    expect(get).toHaveBeenCalledTimes(1)
    expect(dispatch).toHaveBeenCalledWith('clearProfile')
  })

  test('keeps admin pagination scope and explicitly requests the pending review queue', async () => {
    adminClient.mockResolvedValue(response({ items: [], total: 0 }))
    await getKnowledgePointCollection('root', 'prerequisites', 2)
    expect(adminClient).toHaveBeenLastCalledWith(expect.objectContaining({ url: 'knowledge-points/root/dependencies', params: { direction: 'prerequisites', page: 2, page_size: 100 } }))
    await getKnowledgePointCollection('root', 'related_problems', 2)
    expect(adminClient).toHaveBeenLastCalledWith(expect.objectContaining({ url: 'knowledge-points/root/related-problems', params: { page: 2, page_size: 100 } }))
    await listKnowledgeReviews({ status: '', page: 1 })
    expect(adminClient).toHaveBeenLastCalledWith(expect.objectContaining({ params: { status: 'pending', page: 1 } }))
    await listKnowledgeReviews({ status: 'rejected' })
    expect(adminClient).toHaveBeenLastCalledWith(expect.objectContaining({ params: { status: 'rejected' } }))
  })

  test('accepts local 202 mapping submissions and sends the review timestamp unchanged', async () => {
    const mappings = { base_version: 3, mappings: [{ knowledge_code: 'root', role: 'primary', weight: 0.5 }] }
    adminClient.mockResolvedValue(response({ review_batch_id: 'batch', ...mappings }, 202))
    await expect(submitProblemKnowledgeMappings(42, mappings)).resolves.toMatchObject({ review_batch_id: 'batch' })
    expect(adminClient).toHaveBeenLastCalledWith(expect.objectContaining({ method: 'put', url: 'problems/42/knowledge-mappings', data: mappings }))
    const review = { expected_updated_time: '2026-10-11T10:00:00.123456+00:00', reason: '需要修订' }
    await reviewKnowledge('problem_mapping', 'batch', 'reject', review)
    expect(adminClient).toHaveBeenLastCalledWith(expect.objectContaining({ method: 'post', url: 'knowledge-reviews/problem_mapping/batch/reject', data: review }))
  })
})
