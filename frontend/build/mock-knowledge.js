'use strict'

// Public knowledge fixtures for the loopback-only Mock server.
module.exports = function (router, { isLoggedIn, problems, user }) {
  const points = [
    ['graph_basic', '图的基本概念', 'graph', 1, ['图论基础'], '认识顶点、边、有向图与无向图等基本术语。'],
    ['adjacency_representation', '图的邻接表示', 'graph', 1, ['图的存储'], '使用邻接矩阵或邻接表保存图中的边。'],
    ['queue_basic', '队列基础', 'data_structure', 1, ['先进先出'], '理解队列的先进先出顺序及入队、出队操作。'],
    ['recursion_basic', '递归基础', 'basic', 1, ['递归函数'], '理解递归调用、终止条件与调用栈。'],
    ['bfs_basic', 'BFS 基础遍历', 'graph', 2, ['广搜', '宽度优先搜索'], '使用队列逐层访问图中节点，是最短路与连通性问题的基础。'],
    ['grid_bfs', '网格图 BFS', 'graph', 2, ['网格广搜'], '将网格位置视为图的节点，按层扩展相邻位置。'],
    ['bfs_shortest_path', '无权图 BFS 最短路', 'graph', 3, ['无权最短路'], '利用 BFS 的层次顺序求无权图最短路径。'],
    ['multi_source_bfs', '多源 BFS', 'graph', 4, ['多起点广搜'], '从多个起点同时入队，计算到最近起点的距离。'],
    ['dfs_basic', 'DFS 基础遍历', 'graph', 2, ['深搜', '深度优先搜索'], '沿分支深入访问节点，再回溯探索其他分支。'],
    ['dfs_connected_components', 'DFS 连通块', 'graph', 3, ['连通分量'], '通过 DFS 识别无向图或网格中的连通区域。'],
    ['dfs_cycle_detection', 'DFS 环检测', 'graph', 3, ['判环'], '结合访问状态，识别图中是否存在环。'],
    ['topological_sort', '拓扑排序', 'graph', 4, ['拓扑序'], '对有向无环图中的依赖关系给出线性顺序。']
  ].map(([code, name, category, level, aliases, description]) => ({ code, name, description, category, level, aliases }))
  const byCode = Object.fromEntries(points.map(point => [point.code, point]))
  const edges = [
    ['graph_basic', 'adjacency_representation', 'required'],
    ['adjacency_representation', 'bfs_basic', 'required'],
    ['queue_basic', 'bfs_basic', 'recommended'],
    ['bfs_basic', 'grid_bfs', 'required'],
    ['bfs_basic', 'bfs_shortest_path', 'required'],
    ['bfs_shortest_path', 'multi_source_bfs', 'recommended'],
    ['adjacency_representation', 'dfs_basic', 'required'],
    ['recursion_basic', 'dfs_basic', 'recommended'],
    ['dfs_basic', 'dfs_connected_components', 'required'],
    ['dfs_basic', 'dfs_cycle_detection', 'required'],
    ['dfs_cycle_detection', 'topological_sort', 'required']
  ].map(([from, to, relation_type]) => ({ from, to, relation_type, weight: relation_type === 'required' ? 1 : 0.7 }))
  let requestNumber = 0
  const reply = (res, data, status = 200, error = null) => res.status(status).set('X-API-Version', '0.9.9').json({ error, data, request_id: `mock-knowledge-${++requestNumber}` })
  const authorize = (req, res, next) => isLoggedIn() ? next() : reply(res, null, 401, 'KNOWLEDGE_AUTH_REQUIRED')
  const invalid = res => reply(res, null, 400, 'KNOWLEDGE_INPUT_INVALID')
  const notFound = res => reply(res, null, 404, 'KNOWLEDGE_NOT_FOUND')
  const only = (query, allowed) => Object.keys(query).every(key => allowed.includes(key))
  const integer = (value, defaultValue, max) => {
    if (value === undefined) return defaultValue
    if (!/^[1-9]\d*$/.test(String(value))) return null
    const number = Number(value)
    return number <= max ? number : null
  }
  const category = value => value === undefined || ['basic', 'data_structure', 'algorithm', 'paradigm', 'mathematics', 'string', 'graph'].includes(value)
  const level = value => integer(value, undefined, 5)
  const visible = (point, query) => (!query.category || point.category === query.category) && (!query.level || point.level === Number(query.level))

  const now = () => new Date().toISOString()
  const adminPoints = points.map((point, index) => ({
    ...point,
    id: index + 1,
    normalized_name: point.name.toLowerCase().replace(/\s+/g, '_'),
    status: 'active',
    version: 1,
    metadata: {},
    created_time: '2026-09-20T01:00:00Z',
    updated_time: `2026-09-${String(20 + (index % 8)).padStart(2, '0')}T03:00:00Z`
  }))
  adminPoints.push({ id: adminPoints.length + 1, code: 'binary_search_draft', name: '二分查找草稿', normalized_name: '二分查找草稿', description: '等待补充并发布的知识点。', category: 'algorithm', level: 2, aliases: ['二分'], status: 'draft', version: 1, metadata: {}, created_time: '2026-09-28T01:00:00Z', updated_time: '2026-09-28T01:00:00Z' })
  const adminPointByCode = () => Object.fromEntries(adminPoints.map(point => [point.code, point]))
  let adminEdges = edges.map((edge, index) => ({ ...edge, id: index + 1, version: 1, source: 'manual', confidence: 1, updated_time: '2026-09-26T02:00:00Z' }))
  const mappingSets = new Map(problems.map(problem => [String(problem.id), { problem_id: problem.id, coverage_status: 'unannotated', approved_version: 0, next_batch_version: 1, mappings: [], pending_batch: null, capabilities: ['view', 'submit'] }]))
  const bfsProblem = problems.find(problem => problem._id === '1002')
  if (bfsProblem) mappingSets.set(String(bfsProblem.id), { problem_id: bfsProblem.id, coverage_status: 'ready', approved_version: 1, next_batch_version: 2, mappings: [
    { id: 1, knowledge_code: 'bfs_basic', knowledge_name: byCode.bfs_basic.name, role: 'primary', weight: 1, review_status: 'approved', updated_time: '2026-09-25T02:00:00Z' },
    { id: 2, knowledge_code: 'queue_basic', knowledge_name: byCode.queue_basic.name, role: 'prerequisite', weight: 0.6, review_status: 'approved', updated_time: '2026-09-25T02:00:00Z' }
  ], pending_batch: null, capabilities: ['view', 'submit', 'replace_approved'] })
  const reviewItems = [
    { object_type: 'dependency_change', object_key: '11111111-1111-4111-8111-111111111111', object_version: 0, operation: 'create', submitter: { id: 8, username: 'teacher_a' }, target_summary: { label: 'bfs_basic → multi_source_bfs' }, status: 'pending', created_time: '2026-09-29T03:00:00Z', updated_time: '2026-09-29T03:00:00Z', reason: null },
    { object_type: 'problem_mapping', object_key: '22222222-2222-4222-8222-222222222222', object_version: 1, operation: 'replace', submitter: { id: 9, username: 'teacher_b' }, target_summary: { label: problems[2] ? problems[2].title : '连通区域（DFS）' }, status: 'pending', created_time: '2026-09-29T05:00:00Z', updated_time: '2026-09-29T05:00:00Z', reason: null }
  ]
  if (problems[2]) mappingSets.set(String(problems[2].id), { problem_id: problems[2].id, coverage_status: 'in_review', approved_version: 0, next_batch_version: 2, mappings: [], pending_batch: { review_batch_id: reviewItems[1].object_key, problem_id: problems[2].id, batch_version: 1, base_version: 0, approved_version: null, status: 'pending', mappings: [{ knowledge_code: 'dfs_basic', role: 'primary', weight: 1, source: 'manual', confidence: 1 }], reason: null, updated_time: reviewItems[1].updated_time }, capabilities: ['view'] })
  const adminAuthorize = (req, res, next) => {
    if (!isLoggedIn()) return reply(res, null, 401, 'KNOWLEDGE_AUTH_REQUIRED')
    if (!['Admin', 'Super Admin'].includes(user.admin_type) || (user.admin_type !== 'Super Admin' && user.problem_permission === 'None')) return reply(res, null, 403, 'KNOWLEDGE_PERMISSION_DENIED')
    next()
  }
  const superAuthorize = (req, res, next) => {
    if (!isLoggedIn()) return reply(res, null, 401, 'KNOWLEDGE_AUTH_REQUIRED')
    if (user.admin_type !== 'Super Admin') return reply(res, null, 403, 'KNOWLEDGE_PERMISSION_DENIED')
    next()
  }
  const adminPointData = point => ({ ...point })
  const pointCounts = codeValue => ({
    prerequisite_count: adminEdges.filter(edge => edge.to === codeValue).length,
    dependent_count: adminEdges.filter(edge => edge.from === codeValue).length,
    related_problem_count: [...mappingSets.values()].flatMap(set => set.mappings).filter(item => item.knowledge_code === codeValue).length
  })

  router.get('/admin/knowledge-points', adminAuthorize, (req, res) => {
    const pageNumber = integer(req.query.page, 1, 1000000)
    const pageSize = integer(req.query.page_size, 20, 100)
    if (pageNumber === null || pageSize === null || !only(req.query, ['keyword', 'category', 'level', 'status', 'page', 'page_size'])) return invalid(res)
    const keyword = String(req.query.keyword || '').toLowerCase()
    const rows = adminPoints.filter(point => (!req.query.category || point.category === req.query.category) && (!req.query.level || point.level === Number(req.query.level)) && (!req.query.status || point.status === req.query.status) && (!keyword || [point.code, point.name, point.normalized_name, ...point.aliases].some(value => value.toLowerCase().includes(keyword))))
      .sort((left, right) => right.updated_time.localeCompare(left.updated_time) || left.code.localeCompare(right.code))
    reply(res, { items: rows.slice((pageNumber - 1) * pageSize, pageNumber * pageSize).map(point => ({ code: point.code, name: point.name, category: point.category, level: point.level, status: point.status, version: point.version, updated_time: point.updated_time, ...pointCounts(point.code) })), page: pageNumber, page_size: pageSize, total: rows.length })
  })

  router.post('/admin/knowledge-points', superAuthorize, (req, res) => {
    if (!/^[a-z][a-z0-9_]{0,63}$/.test(req.body.code || '') || adminPointByCode()[req.body.code]) return reply(res, null, 409, 'KNOWLEDGE_CODE_CONFLICT')
    const point = { id: adminPoints.length + 1, code: req.body.code, name: req.body.name, normalized_name: req.body.name, description: req.body.description, category: req.body.category, level: Number(req.body.level), aliases: req.body.aliases || [], status: 'draft', version: 1, metadata: req.body.metadata || {}, created_time: now(), updated_time: now() }
    adminPoints.push(point)
    reply(res, adminPointData(point), 201)
  })

  router.get('/admin/knowledge-points/:code', adminAuthorize, (req, res) => {
    const point = adminPointByCode()[req.params.code]
    if (!point) return notFound(res)
    const dep = (edge, otherCode) => ({ dependency_id: edge.id, code: otherCode, name: adminPointByCode()[otherCode].name, relation_type: edge.relation_type, weight: edge.weight, version: edge.version })
    const related = []
    for (const problem of problems) for (const mapping of (mappingSets.get(String(problem.id)) || { mappings: [] }).mappings) if (mapping.knowledge_code === point.code) related.push({ problem_id: problem.id, display_id: problem._id, title: problem.title, role: mapping.role, weight: mapping.weight })
    const capabilities = ['view']
    if (user.admin_type === 'Super Admin') {
      capabilities.push('edit', 'request_dependency_change')
      if (['draft', 'active'].includes(point.status)) capabilities.push('change_status')
      if (point.status === 'draft' && !adminEdges.some(edge => edge.from === point.code || edge.to === point.code) && !related.length) capabilities.push('delete_draft')
    }
    const prerequisites = adminEdges.filter(edge => edge.to === point.code).map(edge => dep(edge, edge.from))
    const dependents = adminEdges.filter(edge => edge.from === point.code).map(edge => dep(edge, edge.to))
    reply(res, { knowledge_point: adminPointData(point), capabilities, prerequisites: { items: prerequisites, total: prerequisites.length }, dependents: { items: dependents, total: dependents.length }, related_problems: { items: related, total: related.length } })
  })

  router.patch('/admin/knowledge-points/:code', superAuthorize, (req, res) => {
    const point = adminPointByCode()[req.params.code]
    if (!point) return notFound(res)
    if (Number(req.body.version) !== point.version) return reply(res, null, 409, 'KNOWLEDGE_VERSION_CONFLICT')
    if (req.body.status && ![["draft", "active"], ["active", "deprecated"]].some(([from, to]) => point.status === from && req.body.status === to)) return reply(res, null, 409, 'KNOWLEDGE_STATE_CONFLICT')
    for (const key of ['name', 'description', 'category', 'level', 'status', 'aliases', 'metadata']) if (req.body[key] !== undefined) point[key] = req.body[key]
    point.version += 1
    point.updated_time = now()
    reply(res, adminPointData(point))
  })

  router.post('/admin/knowledge-points/:code/delete', superAuthorize, (req, res) => {
    const index = adminPoints.findIndex(point => point.code === req.params.code)
    if (index < 0) return notFound(res)
    const point = adminPoints[index]
    if (point.status !== 'draft' || Number(req.body.version) !== point.version || String(req.body.reason || '').trim().length < 2 || adminEdges.some(edge => edge.from === point.code || edge.to === point.code)) return reply(res, null, 409, 'KNOWLEDGE_STATE_CONFLICT')
    adminPoints.splice(index, 1)
    res.status(204).set('X-API-Version', '0.9.9').end()
  })

  router.get('/admin/knowledge-graph', adminAuthorize, (req, res) => {
    const root = req.query.root_code
    if (root && !adminPointByCode()[root]) return notFound(res)
    const maxDepth = integer(req.query.depth, 3, 8)
    const distance = root ? { [root]: 0 } : {}
    const queue = root ? [root] : []
    for (let index = 0; index < queue.length; index++) {
      const current = queue[index]
      if (distance[current] >= maxDepth) continue
      for (const edge of adminEdges) {
        const other = edge.from === current ? edge.to : edge.to === current ? edge.from : null
        if (other && distance[other] === undefined) { distance[other] = distance[current] + 1; queue.push(other) }
      }
    }
    const candidates = adminPoints.filter(point => point.status === 'active' && (!root || distance[point.code] !== undefined) && (point.code === root || (!req.query.category || point.category === req.query.category) && (!req.query.level || point.level === Number(req.query.level))))
    const selected = candidates.slice(0, 500)
    const codes = new Set(selected.map(point => point.code))
    reply(res, { nodes: selected.map(point => ({ code: point.code, name: point.name, level: point.level })), edges: adminEdges.filter(edge => codes.has(edge.from) && codes.has(edge.to)).map(edge => ({ id: edge.id, from: edge.from, to: edge.to, relation_type: edge.relation_type, weight: edge.weight })), truncated: candidates.length > 500 })
  })

  router.post('/admin/knowledge-dependency-change-requests', superAuthorize, (req, res) => {
    const key = `33333333-3333-4333-8333-${String(reviewItems.length + 1).padStart(12, '0')}`
    const item = { object_type: 'dependency_change', object_key: key, object_version: req.body.base_version || 0, operation: req.body.operation, submitter: { id: user.id, username: user.username }, target_summary: { label: req.body.operation === 'delete' ? `Dependency ${req.body.target_dependency_id}` : `${req.body.prerequisite_code} → ${req.body.dependent_code}` }, status: 'pending', created_time: now(), updated_time: now(), reason: null, payload: { ...req.body } }
    reviewItems.unshift(item)
    reply(res, { request_id: key, ...req.body, status: 'pending', submitted_by: item.submitter, created_time: item.created_time, updated_time: item.updated_time }, 201)
  })

  router.get('/admin/problems/:problemId/knowledge-mappings', adminAuthorize, (req, res) => {
    const set = mappingSets.get(String(req.params.problemId))
    if (!set || !problems.some(problem => String(problem.id) === String(req.params.problemId))) return notFound(res)
    reply(res, set)
  })

  router.put('/admin/problems/:problemId/knowledge-mappings', adminAuthorize, (req, res) => {
    const set = mappingSets.get(String(req.params.problemId))
    if (!set) return notFound(res)
    if (set.pending_batch) return reply(res, null, 409, 'KNOWLEDGE_REVIEW_CONFLICT')
    const primaryCount = (req.body.mappings || []).filter(item => item.role === 'primary').length
    if (primaryCount !== 1) return reply(res, null, 422, 'KNOWLEDGE_MAPPING_INVALID')
    const key = `44444444-4444-4444-8444-${String(reviewItems.length + 1).padStart(12, '0')}`
    const batch = { review_batch_id: key, problem_id: Number(req.params.problemId), batch_version: set.next_batch_version, base_version: set.approved_version, approved_version: null, status: 'pending', mappings: req.body.mappings.map(item => ({ ...item, source: 'manual', confidence: 1 })), reason: null, updated_time: now() }
    set.pending_batch = batch
    set.coverage_status = set.mappings.length ? 'ready' : 'in_review'
    set.capabilities = ['view']
    const problem = problems.find(item => String(item.id) === String(req.params.problemId))
    reviewItems.unshift({ object_type: 'problem_mapping', object_key: key, object_version: batch.batch_version, operation: 'replace', submitter: { id: user.id, username: user.username }, target_summary: { label: problem.title }, status: 'pending', created_time: batch.updated_time, updated_time: batch.updated_time, reason: null })
    reply(res, batch, 201)
  })

  router.get('/admin/knowledge-reviews', superAuthorize, (req, res) => {
    const pageNumber = integer(req.query.page, 1, 1000000)
    const pageSize = integer(req.query.page_size, 20, 100)
    const keyword = String(req.query.keyword || '').toLowerCase()
    let rows = reviewItems.filter(item => (!req.query.object_type || item.object_type === req.query.object_type) && (!req.query.status || item.status === req.query.status) && (!req.query.submitter_id || item.submitter.id === Number(req.query.submitter_id)) && (!req.query.updated_from || item.updated_time >= req.query.updated_from) && (!req.query.updated_to || item.updated_time <= req.query.updated_to) && (!keyword || [item.target_summary.label, item.submitter.username, item.object_key].some(value => value.toLowerCase().includes(keyword))))
    rows = rows.sort((left, right) => right.updated_time.localeCompare(left.updated_time))
    reply(res, { items: rows.slice((pageNumber - 1) * pageSize, pageNumber * pageSize), page: pageNumber, page_size: pageSize, total: rows.length })
  })

  router.get('/admin/knowledge-reviews/:type/:key', superAuthorize, (req, res) => {
    const item = reviewItems.find(row => row.object_type === req.params.type && row.object_key === req.params.key)
    if (!item) return notFound(res)
    const capabilities = item.status === 'pending' && item.submitter.id !== user.id ? ['approve', 'reject'] : []
    if (item.object_type === 'dependency_change') {
      const payload = item.payload || { operation: 'create', prerequisite_code: 'bfs_basic', dependent_code: 'multi_source_bfs', relation_type: 'recommended', weight: 0.8, reason: '补充进阶学习关系' }
      const target = payload.target_dependency_id ? adminEdges.find(edge => edge.id === Number(payload.target_dependency_id)) : null
      const snapshot = edge => edge ? { id: edge.id, prerequisite: adminPointData(adminPointByCode()[edge.from]), dependent: adminPointData(adminPointByCode()[edge.to]), relation_type: edge.relation_type, weight: edge.weight, version: edge.version } : null
      const proposed = payload.operation === 'delete' ? null : { prerequisite_code: payload.prerequisite_code, dependent_code: payload.dependent_code, relation_type: payload.relation_type, weight: payload.weight }
      return reply(res, { object_type: item.object_type, request: { request_id: item.object_key, operation: item.operation, target_dependency_id: payload.target_dependency_id || null, base_version: payload.base_version || null, before: snapshot(target), proposed, status: item.status, reason: payload.reason || '补充知识依赖', review_reason: item.reason, submitted_by: item.submitter, reviewed_by: null, created_time: item.created_time, updated_time: item.updated_time }, capabilities })
    }
    const set = [...mappingSets.values()].find(value => value.pending_batch && value.pending_batch.review_batch_id === item.object_key) || mappingSets.get(String(problems[2] && problems[2].id))
    const problem = problems.find(problem => problem.id === set.problem_id)
    reply(res, { object_type: item.object_type, problem: { problem_id: problem.id, display_id: problem._id, title: problem.title }, current_approved_version: set.approved_version, batch: set.pending_batch || { review_batch_id: item.object_key, problem_id: problem.id, batch_version: item.object_version, base_version: set.approved_version, status: item.status, mappings: [], updated_time: item.updated_time }, capabilities })
  })

  router.post('/admin/knowledge-reviews/:type/:key/:action', superAuthorize, (req, res) => {
    const item = reviewItems.find(row => row.object_type === req.params.type && row.object_key === req.params.key)
    if (!item) return notFound(res)
    if (item.submitter.id === user.id) return reply(res, null, 403, 'KNOWLEDGE_SELF_REVIEW_FORBIDDEN')
    if (item.status !== 'pending' || req.body.expected_updated_time !== item.updated_time) return reply(res, null, 409, 'KNOWLEDGE_VERSION_CONFLICT')
    item.status = req.params.action === 'approve' ? 'approved' : 'rejected'
    item.reason = req.body.reason || null
    item.updated_time = now()
    if (item.object_type === 'dependency_change' && req.params.action === 'approve') {
      const payload = item.payload || { operation: 'create', prerequisite_code: 'bfs_basic', dependent_code: 'multi_source_bfs', relation_type: 'recommended', weight: 0.8 }
      if (payload.operation === 'create') {
        adminEdges.push({ id: Math.max(0, ...adminEdges.map(edge => edge.id)) + 1, from: payload.prerequisite_code, to: payload.dependent_code, relation_type: payload.relation_type, weight: payload.weight, version: 1, source: 'manual', confidence: 1, updated_time: item.updated_time })
      } else {
        const edge = adminEdges.find(edge => edge.id === Number(payload.target_dependency_id))
        if (payload.operation === 'delete') adminEdges = adminEdges.filter(candidate => candidate !== edge)
        if (payload.operation === 'update' && edge) Object.assign(edge, { from: payload.prerequisite_code, to: payload.dependent_code, relation_type: payload.relation_type, weight: payload.weight, version: edge.version + 1, updated_time: item.updated_time })
      }
    }
    if (item.object_type === 'problem_mapping') {
      const set = [...mappingSets.values()].find(value => value.pending_batch && value.pending_batch.review_batch_id === item.object_key)
      if (set && req.params.action === 'approve') {
        set.approved_version += 1
        set.mappings = set.pending_batch.mappings.map((mapping, index) => ({ id: index + 10, knowledge_code: mapping.knowledge_code, knowledge_name: adminPointByCode()[mapping.knowledge_code].name, role: mapping.role, weight: mapping.weight, review_status: 'approved', updated_time: item.updated_time }))
        set.coverage_status = 'ready'
      }
      if (set) { set.pending_batch = null; set.capabilities = ['view', 'submit', ...(set.mappings.length ? ['replace_approved'] : [])] }
    }
    reply(res, item)
  })

  router.get('/knowledge-points', authorize, (req, res) => {
    const query = req.query
    const page = integer(query.page, 1, 1000000)
    const pageSize = integer(query.page_size, 20, 100)
    if (!only(query, ['keyword', 'category', 'level', 'page', 'page_size']) || page === null || pageSize === null || !category(query.category) || (query.level !== undefined && level(query.level) === null) || (query.keyword && query.keyword.length > 128)) return invalid(res)
    const keyword = String(query.keyword || '').trim().toLowerCase()
    const filtered = points.filter(point => visible(point, query) && (!keyword || [point.code, point.name, ...point.aliases].some(text => text.toLowerCase().includes(keyword)))).sort((a, b) => a.code.localeCompare(b.code))
    reply(res, { items: filtered.slice((page - 1) * pageSize, page * pageSize), page, page_size: pageSize, total: filtered.length })
  })

  router.get('/knowledge-points/:code', authorize, (req, res) => {
    if (!only(req.query, [])) return invalid(res)
    const point = byCode[req.params.code]
    if (!point) return notFound(res)
    const related = point.code === 'bfs_basic' || point.code === 'grid_bfs' || point.code === 'bfs_shortest_path'
      ? problems.filter(problem => problem._id === '1002')
      : point.code === 'dfs_basic' || point.code === 'dfs_connected_components'
        ? problems.filter(problem => problem._id === '1003') : []
    reply(res, {
      ...point,
      prerequisites: edges.filter(edge => edge.to === point.code).map(edge => ({ code: edge.from, name: byCode[edge.from].name, relation_type: edge.relation_type, weight: edge.weight })).sort((a, b) => a.code.localeCompare(b.code)),
      dependents: edges.filter(edge => edge.from === point.code).map(edge => ({ code: edge.to, name: byCode[edge.to].name, relation_type: edge.relation_type, weight: edge.weight })).sort((a, b) => a.code.localeCompare(b.code)),
      related_problems: related.filter(problem => problem.visible && !problem.contest_id).map(problem => ({ display_id: problem._id, title: problem.title }))
    })
  })

  router.get('/knowledge-graph', authorize, (req, res) => {
    const query = req.query
    const depth = integer(query.depth, 3, 8)
    if (!only(query, ['root_code', 'depth', 'category', 'level']) || depth === null || !category(query.category) || (query.level !== undefined && level(query.level) === null)) return invalid(res)
    if (query.root_code && !byCode[query.root_code]) return notFound(res)
    const distance = {}
    if (query.root_code) {
      distance[query.root_code] = 0
      const queue = [query.root_code]
      for (let index = 0; index < queue.length; index++) {
        const current = queue[index]
        if (distance[current] >= depth) continue
        for (const edge of edges) {
          const other = edge.from === current ? edge.to : edge.to === current ? edge.from : null
          if (other && distance[other] === undefined) { distance[other] = distance[current] + 1; queue.push(other) }
        }
      }
    }
    const candidates = points.filter(point => (!query.root_code || distance[point.code] !== undefined) && (point.code === query.root_code || visible(point, query)))
      .sort((a, b) => (distance[a.code] || 0) - (distance[b.code] || 0) || a.code.localeCompare(b.code))
    const selected = candidates.slice(0, 500)
    const codes = new Set(selected.map(point => point.code))
    reply(res, {
      nodes: selected.map(({ code, name, level }) => ({ code, name, level })),
      edges: edges.filter(edge => codes.has(edge.from) && codes.has(edge.to)).sort((a, b) => a.from.localeCompare(b.from) || a.to.localeCompare(b.to)),
      truncated: candidates.length > 500
    })
  })
}
