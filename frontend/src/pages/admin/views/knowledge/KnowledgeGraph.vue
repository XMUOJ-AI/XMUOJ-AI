<template>
  <div class="view admin-graph-page">
    <Panel title="知识图谱">
      <template #header><el-button @click="$router.push({ name: 'admin-knowledge-list' })">返回知识点列表</el-button></template>
      <el-form class="filters" inline @submit.prevent>
        <el-form-item label="根节点"><el-input v-model="draft.root_code" clearable placeholder="输入知识点编码" @keyup.enter="applyFilters" /></el-form-item>
        <el-form-item label="深度"><el-select v-model="draft.depth" :disabled="!draft.root_code"><el-option v-for="depth in 8" :key="depth" :label="`${depth} 层`" :value="String(depth)" /></el-select></el-form-item>
        <el-form-item label="分类"><el-select v-model="draft.category" clearable placeholder="全部分类"><el-option v-for="item in categories" :key="item[0]" :label="item[1]" :value="item[0]" /></el-select></el-form-item>
        <el-form-item label="层级"><el-select v-model="draft.level" clearable placeholder="全部层级"><el-option v-for="level in 5" :key="level" :label="`L${level}`" :value="String(level)" /></el-select></el-form-item>
        <el-form-item><el-button type="primary" @click="applyFilters">应用筛选</el-button><el-button @click="reset">重置</el-button></el-form-item>
      </el-form>
      <p v-if="!draft.root_code" class="filter-hint">未设置根节点时显示全部正式关系，深度筛选不生效。</p>
      <el-alert v-if="error" :title="error" type="error" show-icon :closable="false" class="state-alert" />
      <el-alert v-if="graph && graph.truncated" title="图谱结果超过 500 个节点，请设置根节点或缩小筛选范围。" type="warning" show-icon :closable="false" class="state-alert" />

      <div class="view-toolbar">
        <el-radio-group v-model="view"><el-radio-button value="graph">图形视图</el-radio-button><el-radio-button value="table">关系表格</el-radio-button></el-radio-group>
        <div v-if="view === 'graph'" class="canvas-actions"><el-button @click="fit">适应画布</el-button><el-button aria-label="缩小" @click="zoom(-0.1)">−</el-button><el-button aria-label="放大" @click="zoom(0.1)">＋</el-button></div>
      </div>

      <div v-loading="loading" class="graph-content" :class="{ 'with-panel': graph && view === 'graph' }">
        <template v-if="graph && view === 'graph'">
          <div class="graph-canvas"><PublicKnowledgeGraph ref="graphView" :graph="graph" :root-code="filters.root_code" :directional="Boolean(filters.root_code)" detail-route-name="admin-knowledge-detail" @select-node="selectNode" /></div>
          <aside class="node-panel">
            <template v-if="selectedLoading"><el-skeleton :rows="6" animated /></template>
            <template v-else-if="selectedDetail">
              <div class="node-title"><div><h2>{{ selectedPoint.name }}</h2><code>{{ selectedPoint.code }}</code></div><el-tag :type="statusType(selectedPoint.status)">{{ labelOf(statusOptions, selectedPoint.status) }}</el-tag></div>
              <p>{{ selectedPoint.description || '暂无描述' }}</p>
              <el-descriptions :column="1" size="small"><el-descriptions-item label="分类">{{ labelOf(categories, selectedPoint.category) }}</el-descriptions-item><el-descriptions-item label="层级">L{{ selectedPoint.level }}</el-descriptions-item><el-descriptions-item label="前置">{{ selectedDetail.prerequisites.total }}</el-descriptions-item><el-descriptions-item label="后继">{{ selectedDetail.dependents.total }}</el-descriptions-item><el-descriptions-item label="关联题目">{{ selectedDetail.related_problems.total }}</el-descriptions-item></el-descriptions>
              <el-button type="primary" plain @click="$router.push({ name: 'admin-knowledge-detail', params: { code: selectedPoint.code } })">查看详情与维护依赖</el-button>
            </template>
            <div v-else class="node-placeholder">点击图中知识点查看摘要</div>
          </aside>
        </template>

        <template v-else-if="graph">
          <h3>知识点（{{ graph.nodes.length }}）</h3>
          <el-table :data="graph.nodes" empty-text="当前范围内没有知识点" stripe>
            <el-table-column prop="code" label="编码" min-width="180"><template #default="{ row }"><code>{{ row.code }}</code></template></el-table-column>
            <el-table-column prop="name" label="名称" min-width="200" />
            <el-table-column label="层级" width="90"><template #default="{ row }">L{{ row.level }}</template></el-table-column>
            <el-table-column label="操作" width="120"><template #default="{ row }"><router-link :to="{ name: 'admin-knowledge-detail', params: { code: row.code } }">查看详情</router-link></template></el-table-column>
          </el-table>
          <h3 class="edge-heading">正式依赖（{{ graph.edges.length }}）</h3>
          <el-table :data="graph.edges" empty-text="当前范围内没有依赖关系" stripe>
            <el-table-column label="前置知识点" min-width="220"><template #default="{ row }"><router-link :to="{ name: 'admin-knowledge-detail', params: { code: row.from } }">{{ nodeName(row.from) }}</router-link><code>{{ row.from }}</code></template></el-table-column>
            <el-table-column label="后继知识点" min-width="220"><template #default="{ row }"><router-link :to="{ name: 'admin-knowledge-detail', params: { code: row.to } }">{{ nodeName(row.to) }}</router-link><code>{{ row.to }}</code></template></el-table-column>
            <el-table-column label="类型" width="120"><template #default="{ row }">{{ row.relation_type === 'required' ? '必需依赖' : '推荐依赖' }}</template></el-table-column>
            <el-table-column prop="weight" label="权重" width="90" />
          </el-table>
        </template>
      </div>
      <div class="legend"><span><i class="solid"></i> 必需依赖</span><span><i class="dashed"></i> 推荐依赖</span><span>图中只展示审核通过的正式依赖</span></div>
    </Panel>
  </div>
</template>

<script>
  import PublicKnowledgeGraph from '@oj/views/knowledge/KnowledgeGraph.vue'
  import { getAdminKnowledgeGraph, getKnowledgePoint } from './knowledgeAdminApi'
  import { categories, compactParams, errorText, labelOf, statusOptions, statusType } from './knowledgeAdminData'

  export default {
    name: 'AdminKnowledgeGraph',
    components: { PublicKnowledgeGraph },
    data () {
      return {
        categories,
        statusOptions,
        loading: false,
        selectedLoading: false,
        error: '',
        graph: null,
        view: 'graph',
        filters: { root_code: '', depth: '3', category: '', level: '' },
        draft: { root_code: '', depth: '3', category: '', level: '' },
        selectedDetail: null,
        detailRequest: 0
      }
    },
    computed: { selectedPoint () { return this.selectedDetail && this.selectedDetail.knowledge_point } },
    watch: { '$route.query': { handler () { this.restore(); this.load() }, deep: true } },
    created () { this.restore(); this.load() },
    methods: {
      labelOf,
      statusType,
      restore () {
        const query = this.$route.query
        this.filters = { root_code: query.root_code || '', depth: query.depth || '3', category: query.category || '', level: query.level || '' }
        this.draft = { ...this.filters }
      },
      async load () {
        this.loading = true
        this.error = ''
        try {
          const params = compactParams({ ...this.filters, depth: this.filters.root_code ? this.filters.depth : '' })
          this.graph = await getAdminKnowledgeGraph(params)
          const selected = this.filters.root_code && this.graph.nodes.some(item => item.code === this.filters.root_code) ? this.filters.root_code : ''
          this.selectedDetail = null
          if (selected) await this.loadDetail(selected)
        } catch (error) { this.graph = null; this.error = errorText(error) } finally { this.loading = false }
      },
      applyFilters () { this.$router.push({ name: 'admin-knowledge-graph', query: compactParams({ ...this.draft, depth: this.draft.root_code ? this.draft.depth : '' }) }) },
      reset () { this.$router.push({ name: 'admin-knowledge-graph' }) },
      async selectNode (code) { await this.loadDetail(code) },
      async loadDetail (code) {
        const request = ++this.detailRequest
        this.selectedLoading = true
        try { const detail = await getKnowledgePoint(code); if (request === this.detailRequest) this.selectedDetail = detail } catch (error) { if (request === this.detailRequest) this.$error(errorText(error)) } finally { if (request === this.detailRequest) this.selectedLoading = false }
      },
      fit () { this.$refs.graphView && this.$refs.graphView.fit() },
      zoom (step) { this.$refs.graphView && this.$refs.graphView.zoom(step) },
      nodeName (code) { const node = this.graph.nodes.find(item => item.code === code); return node ? node.name : code }
    }
  }
</script>

<style scoped lang="less">
  .filters, .view-toolbar, .canvas-actions, .node-title, .legend { display: flex; align-items: center; }
  .filters { flex-wrap: wrap; gap: 0 8px; }
  .filters :deep(.el-input) { width: 220px; }
  .filters :deep(.el-select) { width: 150px; }
  .filter-hint { color: #909399; margin: -4px 0 14px; }
  .state-alert { margin-bottom: 14px; }
  .view-toolbar { justify-content: space-between; margin-bottom: 14px; }
  .canvas-actions { gap: 8px; }
  .graph-content { min-height: 420px; }
  .graph-canvas { height: 560px; min-width: 0; border: 1px solid #e4e7ed; border-radius: 6px; overflow: hidden; }
  .graph-content.with-panel { display: grid; grid-template-columns: minmax(0, 1fr) 290px; gap: 16px; }
  .node-panel { border: 1px solid #e4e7ed; border-radius: 6px; padding: 18px; background: #fafcff; }
  .node-title { align-items: flex-start; justify-content: space-between; gap: 12px; }
  .node-title h2 { margin: 0 0 5px; font-size: 19px; }
  .node-panel p { min-height: 60px; color: #606266; line-height: 1.7; }
  .node-placeholder { min-height: 300px; display: grid; place-items: center; color: #909399; }
  code { display: block; color: #8492a6; font-family: Consolas, monospace; }
  .edge-heading { margin-top: 28px; }
  .legend { justify-content: flex-end; gap: 22px; color: #7c899b; margin-top: 14px; }
  .legend i { display: inline-block; width: 32px; border-top: 2px solid #8291a6; vertical-align: middle; }
  .legend i.dashed { border-top-style: dashed; }
  a { color: #409eff; }
</style>
