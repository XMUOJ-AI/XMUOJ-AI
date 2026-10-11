import axios from 'axios'
import store from '@/store'

// Knowledge endpoints have their own envelope. Keep the legacy ajax adapter intact.
export async function knowledgeRequest (url, params) {
  try {
    const response = await axios.get(url, { params, timeout: 15000 })
    const body = response.data
    if (response.status === 204) return null
    if (!body || body.error !== null) {
      throw Object.assign(new Error(body && body.error ? body.error : '知识点请求失败'), {
        status: response.status,
        code: body && body.error,
        requestId: body && body.request_id
      })
    }
    return body.data
  } catch (error) {
    const status = error.status || (error.response && error.response.status)
    const body = error.response && error.response.data
    if (status === 401) {
      store.dispatch('clearProfile')
      store.dispatch('changeModalStatus', { mode: 'login', visible: true })
    }
    throw Object.assign(error, {
      status,
      code: error.code || (body && body.error),
      requestId: error.requestId || (body && body.request_id),
      message: body && body.error ? body.error : error.message
    })
  }
}

export const listKnowledge = params => knowledgeRequest('knowledge-points', params)
export const getKnowledge = (code, params) => knowledgeRequest(`knowledge-points/${encodeURIComponent(code)}`, params)
export const getKnowledgeGraph = params => knowledgeRequest('knowledge-graph', params)

export const getKnowledgeCollection = (code, collection, page = 1) => {
  const base = `knowledge-points/${encodeURIComponent(code)}`
  return collection === 'related_problems'
    ? knowledgeRequest(`${base}/related-problems`, { page, page_size: 20 })
    : knowledgeRequest(`${base}/dependencies`, { direction: collection, page, page_size: 20 })
}

export async function loadKnowledgeDetail (code) {
  const names = ['prerequisites', 'dependents', 'related_problems']
  try {
    const point = await getKnowledge(code)
    return { point, collections: Object.fromEntries(names.map(name => [name, {
      items: point[name], total: point[name].length, page: 1, page_size: 100, loading: false, error: ''
    }])) }
  } catch (error) {
    if (error.code !== 'KNOWLEDGE_PAGINATION_REQUIRED') throw error
    const [point, ...pages] = await Promise.all([
      getKnowledge(code, { include_collections: false }),
      ...names.map(name => getKnowledgeCollection(code, name))
    ])
    return { point, collections: Object.fromEntries(names.map((name, index) => [name, {
      ...pages[index], loading: false, error: ''
    }])) }
  }
}
