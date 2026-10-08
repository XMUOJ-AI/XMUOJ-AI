import axios from 'axios'

const client = axios.create({
  baseURL: '/api/admin',
  xsrfHeaderName: 'X-CSRFToken',
  xsrfCookieName: 'csrftoken'
})

export class KnowledgeAdminError extends Error {
  constructor (response) {
    const body = response && response.data ? response.data : {}
    super(body.error || body.data || 'KNOWLEDGE_REQUEST_FAILED')
    this.name = 'KnowledgeAdminError'
    this.code = body.error || 'KNOWLEDGE_REQUEST_FAILED'
    this.status = response ? response.status : 0
    this.requestId = body.request_id || ''
  }
}

async function request (method, url, options = {}) {
  try {
    const response = await client({ method, url, params: options.params, data: options.data })
    if (response.status === 204) return null
    if (response.data && response.data.error) throw new KnowledgeAdminError(response)
    return response.data ? response.data.data : null
  } catch (error) {
    if (error instanceof KnowledgeAdminError) throw error
    throw new KnowledgeAdminError(error.response)
  }
}

export const listKnowledgePoints = params => request('get', 'knowledge-points', { params })
export const createKnowledgePoint = data => request('post', 'knowledge-points', { data })
export const getKnowledgePoint = code => request('get', `knowledge-points/${encodeURIComponent(code)}`)
export const updateKnowledgePoint = (code, data) => request('patch', `knowledge-points/${encodeURIComponent(code)}`, { data })
export const deleteKnowledgePoint = (code, data) => request('post', `knowledge-points/${encodeURIComponent(code)}/delete`, { data })
export const getAdminKnowledgeGraph = params => request('get', 'knowledge-graph', { params })
export const submitDependencyChange = data => request('post', 'knowledge-dependency-change-requests', { data })
export const getProblemKnowledgeMappings = problemId => request('get', `problems/${problemId}/knowledge-mappings`)
export const submitProblemKnowledgeMappings = (problemId, data) => request('put', `problems/${problemId}/knowledge-mappings`, { data })
export const listKnowledgeReviews = params => request('get', 'knowledge-reviews', { params })
export const getKnowledgeReview = (type, key) => request('get', `knowledge-reviews/${type}/${key}`)
export const reviewKnowledge = (type, key, action, data) => request('post', `knowledge-reviews/${type}/${key}/${action}`, { data })

