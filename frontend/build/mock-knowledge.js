'use strict'

// Public knowledge fixtures for the loopback-only Mock server.
module.exports = function (router, { isLoggedIn, problems }) {
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
