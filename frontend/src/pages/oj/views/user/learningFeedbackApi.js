import axios from 'axios'

// Proposed contract: identity and permissions are resolved by the server session.
// Isolated client avoids the shared API's global error dialogs and baseURL.
const client = axios.create({ baseURL: '', timeout: 20000, xsrfHeaderName: 'X-CSRFToken', xsrfCookieName: 'csrftoken' })
const params = scenario => process.env.AI_FEATURES_MOCK === true && typeof scenario === 'string' ? { mock_feedback: scenario } : {}

async function request (method, url, scenario, data) {
  const res = await client.request({ method, url, params: params(scenario), data })
  if (!res.data || res.data.error) throw Object.assign(new Error('Feedback unavailable'), { code: res.data && res.data.error })
  return res.data.data
}

export default {
  summary: scenario => request('get', '/api/learning-feedback', scenario),
  generate: scenario => request('post', '/api/learning-feedback/generations', scenario, {}),
  result: (generationId, scenario) => request('get', '/api/learning-feedback/generations/' + encodeURIComponent(generationId), scenario)
}
