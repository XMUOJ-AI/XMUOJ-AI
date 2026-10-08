<template>
  <div class="view knowledge-reviews-page">
    <Panel title="知识审核">
      <template #header><el-tag type="danger">仅 Super Admin</el-tag></template>
      <el-form class="filters" inline @submit.prevent>
        <el-form-item label="关键词"><el-input v-model="draft.keyword" clearable placeholder="目标、提交人或对象编号" @keyup.enter="applyFilters" /></el-form-item>
        <el-form-item label="对象类型"><el-select v-model="draft.object_type" clearable placeholder="全部类型"><el-option label="依赖变更" value="dependency_change" /><el-option label="题目标注" value="problem_mapping" /></el-select></el-form-item>
        <el-form-item label="状态"><el-select v-model="draft.status" clearable placeholder="全部状态"><el-option v-for="item in reviewStatuses" :key="item[0]" :label="item[1]" :value="item[0]" /></el-select></el-form-item>
        <el-form-item label="提交人 ID"><el-input v-model="draft.submitter_id" clearable placeholder="用户 ID" /></el-form-item>
        <el-form-item label="更新时间从"><el-date-picker v-model="draft.updated_from" type="datetime" placeholder="开始时间" /></el-form-item>
        <el-form-item label="至"><el-date-picker v-model="draft.updated_to" type="datetime" placeholder="结束时间" /></el-form-item>
        <el-form-item><el-button type="primary" @click="applyFilters">查询</el-button><el-button @click="resetFilters">重置</el-button></el-form-item>
      </el-form>

      <el-alert v-if="error" :title="error" type="error" show-icon :closable="false" class="state-alert" />
      <el-table v-loading="loading" :data="items" empty-text="当前筛选条件下没有审核对象" stripe>
        <el-table-column label="类型" width="110"><template #default="{ row }"><el-tag :type="row.object_type === 'dependency_change' ? 'primary' : 'success'">{{ typeLabel(row.object_type) }}</el-tag></template></el-table-column>
        <el-table-column label="目标" min-width="230"><template #default="{ row }"><strong>{{ row.target_summary.label }}</strong><small>{{ row.object_key }}</small></template></el-table-column>
        <el-table-column label="操作" width="100"><template #default="{ row }">{{ operationLabel(row.operation) }}</template></el-table-column>
        <el-table-column label="提交人" width="140"><template #default="{ row }">{{ row.submitter.username }} <small>#{{ row.submitter.id }}</small></template></el-table-column>
        <el-table-column label="状态" width="100"><template #default="{ row }"><el-tag :type="reviewStatusType(row.status)">{{ labelOf(reviewStatuses, row.status) }}</el-tag></template></el-table-column>
        <el-table-column label="更新时间" min-width="170"><template #default="{ row }">{{ localDateTime(row.updated_time) }}</template></el-table-column>
        <el-table-column label="操作" width="100" fixed="right"><template #default="{ row }"><el-button link type="primary" @click="openDetail(row)">审核详情</el-button></template></el-table-column>
      </el-table>
      <div class="pagination-row"><el-pagination v-model:current-page="page" v-model:page-size="pageSize" :page-sizes="[10, 20, 50, 100]" :total="total" layout="total, sizes, prev, pager, next" @current-change="changePage" @size-change="changePageSize" /></div>
    </Panel>

    <el-drawer v-model="detailVisible" title="审核详情" size="620px" @closed="detail = null">
      <div v-loading="detailLoading" class="review-detail">
        <template v-if="detail">
          <div class="detail-heading"><el-tag :type="detail.object_type === 'dependency_change' ? 'primary' : 'success'">{{ typeLabel(detail.object_type) }}</el-tag><el-tag :type="reviewStatusType(detailStatus)">{{ labelOf(reviewStatuses, detailStatus) }}</el-tag></div>

          <template v-if="detail.object_type === 'dependency_change'">
            <el-descriptions :column="1" border>
              <el-descriptions-item label="操作">{{ operationLabel(detail.request.operation) }}</el-descriptions-item>
              <el-descriptions-item label="提交人">{{ detail.request.submitted_by.username }}</el-descriptions-item>
              <el-descriptions-item label="申请原因">{{ detail.request.reason }}</el-descriptions-item>
              <el-descriptions-item label="基础版本">{{ detail.request.base_version || 0 }}</el-descriptions-item>
              <el-descriptions-item label="提交时间">{{ localDateTime(detail.request.created_time) }}</el-descriptions-item>
            </el-descriptions>
            <h3>当前正式关系</h3>
            <DependencySnapshot :value="detail.request.before" empty-text="当前没有正式关系" />
            <h3>拟变更内容</h3>
            <DependencySnapshot :value="detail.request.proposed" empty-text="批准后删除该正式关系" />
          </template>

          <template v-else>
            <el-descriptions :column="1" border>
              <el-descriptions-item label="题目">{{ detail.problem.display_id }} · {{ detail.problem.title }}</el-descriptions-item>
              <el-descriptions-item label="批次版本">{{ detail.batch.batch_version }}</el-descriptions-item>
              <el-descriptions-item label="基于版本">{{ detail.batch.base_version }}</el-descriptions-item>
              <el-descriptions-item label="当前批准版本">{{ detail.current_approved_version }}</el-descriptions-item>
              <el-descriptions-item label="提交时间">{{ localDateTime(detail.batch.updated_time) }}</el-descriptions-item>
            </el-descriptions>
            <h3>整组拟提交映射</h3>
            <el-table :data="detail.batch.mappings" size="small">
              <el-table-column prop="knowledge_code" label="知识点" min-width="180" />
              <el-table-column label="角色" width="120"><template #default="{ row }">{{ roleLabel(row.role) }}</template></el-table-column>
              <el-table-column prop="weight" label="权重" width="80" />
            </el-table>
          </template>

          <el-alert v-if="detailStatus !== 'pending'" :title="`该申请已${labelOf(reviewStatuses, detailStatus)}，无法再次处理。`" type="info" :closable="false" class="action-note" />
          <el-alert v-else-if="!detail.capabilities.length" title="提交人不能审核自己的申请。" type="warning" :closable="false" class="action-note" />
          <div v-else class="review-actions"><el-button type="danger" plain :loading="acting" @click="reject">驳回申请</el-button><el-button type="success" :loading="acting" @click="approve">确认通过</el-button></div>
        </template>
      </div>
    </el-drawer>
  </div>
</template>

<script>
  import { defineComponent, h } from 'vue'
  import { getKnowledgeReview, listKnowledgeReviews, reviewKnowledge } from './knowledgeAdminApi'
  import { compactParams, errorText, labelOf, localDateTime } from './knowledgeAdminData'

  const DependencySnapshot = defineComponent({
    name: 'DependencySnapshot',
    props: { value: Object, emptyText: String },
    setup (props) {
      return () => props.value
        ? h('div', { class: 'dependency-snapshot' }, [
          h('strong', `${props.value.prerequisite?.name || props.value.prerequisite_code} → ${props.value.dependent?.name || props.value.dependent_code}`),
          h('code', `${props.value.prerequisite?.code || props.value.prerequisite_code} → ${props.value.dependent?.code || props.value.dependent_code}`),
          h('span', `${props.value.relation_type === 'required' ? '必需依赖' : '推荐依赖'} · 权重 ${props.value.weight}`)
        ])
        : h('div', { class: 'dependency-snapshot empty' }, props.emptyText)
    }
  })

  export default {
    name: 'KnowledgeReviews',
    components: { DependencySnapshot },
    data () {
      return {
        reviewStatuses: [['pending', '待审核'], ['approved', '已通过'], ['rejected', '已驳回'], ['superseded', '已替换']],
        loading: false,
        detailLoading: false,
        acting: false,
        error: '',
        items: [],
        total: 0,
        page: 1,
        pageSize: 20,
        draft: { keyword: '', object_type: '', status: 'pending', submitter_id: '', updated_from: null, updated_to: null },
        detailVisible: false,
        detail: null,
        currentRow: null
      }
    },
    computed: {
      detailStatus () { return this.detail && (this.detail.object_type === 'dependency_change' ? this.detail.request.status : this.detail.batch.status) }
    },
    watch: { '$route.query': { handler () { this.restore(); this.load() }, deep: true } },
    created () { this.restore(); this.load() },
    methods: {
      labelOf,
      localDateTime,
      typeLabel (value) { return value === 'dependency_change' ? '依赖变更' : '题目标注' },
      operationLabel (value) { return ({ create: '新增', update: '变更', delete: '删除', replace: '整组替换' })[value] || value },
      roleLabel (value) { return ({ primary: '主知识点', secondary: '次要知识点', prerequisite: '前置映射' })[value] || value },
      reviewStatusType (value) { return value === 'approved' ? 'success' : value === 'rejected' ? 'danger' : value === 'pending' ? 'warning' : 'info' },
      restore () {
        const query = this.$route.query
        this.page = Math.max(1, Number(query.page) || 1)
        this.pageSize = [10, 20, 50, 100].includes(Number(query.page_size)) ? Number(query.page_size) : 20
        this.draft = { keyword: query.keyword || '', object_type: query.object_type || '', status: query.status === undefined ? 'pending' : query.status, submitter_id: query.submitter_id || '', updated_from: query.updated_from ? new Date(query.updated_from) : null, updated_to: query.updated_to ? new Date(query.updated_to) : null }
      },
      queryValues (overrides = {}) {
        return compactParams({ keyword: this.draft.keyword, object_type: this.draft.object_type, status: this.draft.status, submitter_id: this.draft.submitter_id, updated_from: this.draft.updated_from ? this.draft.updated_from.toISOString() : '', updated_to: this.draft.updated_to ? this.draft.updated_to.toISOString() : '', page: this.page > 1 ? this.page : '', page_size: this.pageSize !== 20 ? this.pageSize : '', ...overrides })
      },
      async load () {
        this.loading = true
        this.error = ''
        try {
          const data = await listKnowledgeReviews({ ...this.queryValues(), page: this.page, page_size: this.pageSize })
          this.items = data.items
          this.total = data.total
        } catch (error) { this.items = []; this.total = 0; this.error = errorText(error) } finally { this.loading = false }
      },
      applyFilters () { this.$router.push({ name: 'admin-knowledge-reviews', query: this.queryValues({ page: '' }) }) },
      resetFilters () { this.$router.push({ name: 'admin-knowledge-reviews', query: { status: 'pending' } }) },
      changePage (page) { this.$router.push({ name: 'admin-knowledge-reviews', query: this.queryValues({ page: page > 1 ? page : '' }) }) },
      changePageSize (size) { this.$router.push({ name: 'admin-knowledge-reviews', query: this.queryValues({ page: '', page_size: size !== 20 ? size : '' }) }) },
      async openDetail (row) {
        this.currentRow = row
        this.detailVisible = true
        await this.refreshDetail()
      },
      async refreshDetail () {
        this.detailLoading = true
        try { this.detail = await getKnowledgeReview(this.currentRow.object_type, this.currentRow.object_key) } catch (error) { this.$error(errorText(error)); this.detailVisible = false } finally { this.detailLoading = false }
      },
      async approve () {
        const target = this.currentRow.target_summary.label
        try { await this.$confirm(`确认通过“${target}”的${this.typeLabel(this.currentRow.object_type)}申请？批准后将更新正式数据。`, '通过审核', { type: 'warning', confirmButtonText: '确认通过' }) } catch (_) { return }
        await this.act('approve', {})
      },
      async reject () {
        try {
          const result = await this.$prompt('请填写具体驳回原因（2 至 500 字）', `驳回“${this.currentRow.target_summary.label}”`, { inputType: 'textarea', inputPattern: /^.{2,500}$/s, inputErrorMessage: '驳回原因需要 2 至 500 字', confirmButtonText: '确认驳回' })
          await this.act('reject', { reason: result.value.trim() })
        } catch (_) {}
      },
      async act (action, values) {
        this.acting = true
        try {
          const updatedTime = this.detail.object_type === 'dependency_change' ? this.detail.request.updated_time : this.detail.batch.updated_time
          await reviewKnowledge(this.currentRow.object_type, this.currentRow.object_key, action, { expected_updated_time: updatedTime, ...values })
          this.$success(action === 'approve' ? '审核已通过' : '申请已驳回')
          await Promise.all([this.refreshDetail(), this.load()])
        } catch (error) {
          this.$error(errorText(error))
          if (error.status === 409) await Promise.all([this.refreshDetail(), this.load()])
        } finally { this.acting = false }
      }
    }
  }
</script>

<style scoped lang="less">
  .filters { display: flex; flex-wrap: wrap; gap: 0 8px; }
  .filters :deep(.el-input), .filters :deep(.el-select) { width: 190px; }
  .state-alert { margin-bottom: 14px; }
  small, code { display: block; color: #909399; font-family: Consolas, monospace; }
  .pagination-row { display: flex; justify-content: flex-end; margin-top: 18px; }
  .review-detail { min-height: 360px; }
  .detail-heading { display: flex; gap: 8px; margin-bottom: 18px; }
  .review-detail h3 { margin: 24px 0 10px; font-size: 15px; }
  :deep(.dependency-snapshot) { display: flex; flex-direction: column; gap: 7px; padding: 14px; border: 1px solid #dcdfe6; border-radius: 5px; background: #fafcff; }
  :deep(.dependency-snapshot.empty) { color: #909399; }
  .action-note { margin-top: 22px; }
  .review-actions { display: flex; justify-content: flex-end; gap: 12px; margin-top: 24px; padding-top: 18px; border-top: 1px solid #ebeef5; }
</style>
