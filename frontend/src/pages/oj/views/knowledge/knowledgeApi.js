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
      requestId: error.requestId || (body && body.request_id),
      message: body && body.error ? body.error : error.message
    })
  }
}

export const listKnowledge = params => knowledgeRequest('knowledge-points', params)
export const getKnowledge = code => knowledgeRequest(`knowledge-points/${encodeURIComponent(code)}`)
export const getKnowledgeGraph = params => knowledgeRequest('knowledge-graph', params)
