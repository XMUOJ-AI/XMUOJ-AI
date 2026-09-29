const NODE_WIDTH = 156
const NODE_HEIGHT = 52
const COLUMN_GAP = 220
const ROW_GAP = 92

export function layoutKnowledgeGraph (graph, rootCode, directional = false) {
  const nodes = graph.nodes || []
  const edges = graph.edges || []
  const byCode = Object.fromEntries(nodes.map(node => [node.code, node]))
  const positions = {}

  if (directional && rootCode && byCode[rootCode]) {
    const layers = { [rootCode]: 0 }
    for (const [direction, sign] of [['upstream', -1], ['downstream', 1]]) {
      const queue = [rootCode]
      const visited = new Set(queue)
      for (let index = 0; index < queue.length; index++) {
        const current = queue[index]
        for (const edge of edges) {
          const next = direction === 'upstream' && edge.to === current ? edge.from
            : direction === 'downstream' && edge.from === current ? edge.to : null
          if (next && byCode[next] && !visited.has(next)) {
            visited.add(next)
            if (layers[next] === undefined) layers[next] = sign * (Math.abs(layers[current]) + 1)
            queue.push(next)
          }
        }
      }
    }
    const maxLayer = Math.max(0, ...Object.values(layers).map(Math.abs))
    const groups = {}
    for (const [code, layer] of Object.entries(layers)) (groups[layer] ||= []).push(byCode[code])
    const maxRows = Math.max(...Object.values(groups).map(group => group.length))
    const width = maxLayer * COLUMN_GAP * 2 + NODE_WIDTH + 80
    const height = Math.max(180, maxRows * ROW_GAP + 80)
    for (const [layer, group] of Object.entries(groups)) {
      group.sort((a, b) => a.code.localeCompare(b.code))
      group.forEach((node, index) => {
        positions[node.code] = {
          ...node,
          x: width / 2 - NODE_WIDTH / 2 + Number(layer) * COLUMN_GAP,
          y: height / 2 - NODE_HEIGHT / 2 + (index - (group.length - 1) / 2) * ROW_GAP
        }
      })
    }
    return { nodes: Object.values(positions), edges: positionedEdges(edges, positions), width, height }
  }

  const columns = Math.min(5, Math.max(1, nodes.length))
  const width = Math.max(880, columns * COLUMN_GAP + 40)
  const height = Math.max(360, Math.ceil(nodes.length / columns) * ROW_GAP + 80)
  nodes.slice().sort((a, b) => a.code.localeCompare(b.code)).forEach((node, index) => {
    positions[node.code] = {
      ...node,
      x: width / 2 - (columns * COLUMN_GAP) / 2 + (index % columns) * COLUMN_GAP + 32,
      y: 40 + Math.floor(index / columns) * ROW_GAP
    }
  })
  return { nodes: Object.values(positions), edges: positionedEdges(edges, positions), width, height }
}

function positionedEdges (edges, positions) {
  return edges.filter(edge => positions[edge.from] && positions[edge.to]).map(edge => {
    const from = positions[edge.from]
    const to = positions[edge.to]
    if (from.x === to.x) {
      const down = to.y > from.y
      return { ...edge, x1: from.x + NODE_WIDTH / 2, y1: from.y + (down ? NODE_HEIGHT : 0), x2: to.x + NODE_WIDTH / 2, y2: to.y + (down ? -8 : NODE_HEIGHT + 8) }
    }
    const right = to.x > from.x
    return { ...edge, x1: from.x + (right ? NODE_WIDTH : 0), y1: from.y + NODE_HEIGHT / 2, x2: to.x + (right ? -8 : NODE_WIDTH + 8), y2: to.y + NODE_HEIGHT / 2 }
  })
}
