import axios from 'axios'

/* Proposed contract (no real backend/LLM in this feature):
 * GET /api/problem-guidance reads an existing session or starts its thinking timer;
 * it NEVER generates a hint. Query: problem_id (display ID), optional contest_id.
 * POST /api/problem-guidance/messages uses the same query and JSON body
 * { session_id, request_id, text }. Repeating a request_id with the same text is
 * idempotent. A changed text/session must not reuse the request_id.
 * Identity comes from server authentication, not request parameters. Both replies
 * use { error: null, data: { user_id, context: { problem_id, contest_id: ID|null },
 * session_id, capabilities: { can_request, contest_allowed }, status, stage,
 * quota: { limit, remaining }, available_at: ISO|null, server_time: ISO,
 * messages: [{ id, role: 'student'|'guide', stage, text }], last_request_id,
 * message } }. stage is understand/knowledge/direction; see the adapter for states.
 * Server enforces access, contest policy, session association, available_at,
 * quota and idempotency on EVERY POST. Text insufficiency does not consume quota.
 * 401/403/404/409/429 reject the operation; transient 5xx can retry the same ID.
 * Production must define AI_FEATURES_MOCK=false. The mock query is dev-only.
 */
// Isolate from the shared /api baseURL and global response side effects.
const client = axios.create({ baseURL: '', timeout: 20000, xsrfHeaderName: 'X-CSRFToken', xsrfCookieName: 'csrftoken' })
function params (context, scenario) {
  const result = { problem_id: context.problem_id }
  if (context.contest_id) result.contest_id = context.contest_id
  if (process.env.AI_FEATURES_MOCK === true && typeof scenario === 'string' && scenario) result.mock_guidance = scenario
  return result
}
function unwrap (response) {
  if (!response || !response.data || response.data.error) {
    throw Object.assign(new Error('Guidance request failed'), { code: response && response.data && response.data.error })
  }
  return response.data.data
}
export default {
  get (context, scenario) {
    return client.get('/api/problem-guidance', { params: params(context, scenario) }).then(unwrap)
  },
  send (context, scenario, payload) {
    return client.post('/api/problem-guidance/messages', payload, { params: params(context, scenario) }).then(unwrap)
  }
}
