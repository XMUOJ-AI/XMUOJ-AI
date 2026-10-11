import axios from 'axios'
import {ANALYSIS_VERSION, isObject} from './submissionAnalysisData'

// Separate instance avoids global /api baseURL changes or shared error popups.
const client = axios.create({baseURL: '/', timeout: 15000, xsrfHeaderName: 'X-CSRFToken', xsrfCookieName: 'csrftoken'})
export function analysisParams (submissionId, scenario) {
  const params = {submission_id: submissionId, analysis_version: ANALYSIS_VERSION}
  if (process.env.AI_FEATURES_MOCK === true && typeof scenario === 'string') params.mock_analysis = scenario
  return params
}
function request (options) {
  return client(options).then(response => {
    const body = response.data
    if (!isObject(body) || body.error !== null || !isObject(body.data)) {
      const error = new Error('invalid_response')
      error.code = isObject(body) && typeof body.error === 'string' ? body.error : 'invalid_response'
      throw error
    }
    return body.data
  }, error => {
    const body = error.response && error.response.data
    if (isObject(body) && typeof body.error === 'string') error.code = body.error
    throw error
  })
}
export default {
  capability: (submissionId, scenario) => request({method: 'get', url: '/api/submission-analysis', params: analysisParams(submissionId, scenario)}),
  generate: (identity, scenario) => request({method: 'post', url: '/api/submission-analysis/generate', params: analysisParams(identity.submission_id, scenario), data: identity})
}
