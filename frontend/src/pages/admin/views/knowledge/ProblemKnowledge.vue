<template>
  <div class="view problem-knowledge-page">
    <div class="page-nav"><el-button link type="primary" @click="$router.push({ name: 'problem-list' })">← 返回题目列表</el-button></div>
    <el-alert v-if="error" :title="error" type="error" show-icon :closable="false" class="state-alert" />
    <div v-loading="loading">
      <template v-if="mappingSet">
        <Panel title="题目标注">
          <el-descriptions :column="3" border>
            <el-descriptions-item label="题号">{{ problem._id || problem.id }}</el-descriptions-item>
            <el-descriptions-item label="标题">{{ problem.title }}</el-descriptions-item>
            <el-descriptions-item label="公开状态"><el-tag :type="problem.visible ? 'success' : 'info'">{{ problem.visible ? '公开' : '隐藏' }}</el-tag></el-descriptions-item>
            <el-descriptions-item label="难度">{{ problem.difficulty || '—' }}</el-descriptions-item>
            <el-descriptions-item label="创建人">{{ problem.created_by && problem.created_by.username || '—' }}</el-descriptions-item>
            <el-descriptions-item label="当前版本">{{ mappingSet.approved_version }}</el-descriptions-item>
            <el-descriptions-item label="题目标签" :span="3"><el-tag v-for="tag in problem.tags || []" :key="tag" size="small" class="problem-tag">{{ tag }}</el-tag><span v-if="!problem.tags || !problem.tags.length">—</span></el-descriptions-item>
          </el-descriptions>
        </Panel>

        <Panel title="当前已生效映射">
          <template #header><el-tag :type="coverageType">{{ coverageLabel }}</el-tag></template>
          <el-table :data="mappingSet.mappings" empty-text="该题目尚未标注知识点">
            <el-table-column prop="knowledge_code" label="知识点编码" min-width="180"><template #default="{ row }"><router-link :to="{ name: 'admin-knowledge-detail', params: { code: row.knowledge_code } }">{{ row.knowledge_code }}</router-link></template></el-table-column>
            <el-table-column prop="knowledge_name" label="知识点名称" min-width="190" />
            <el-table-column label="角色" width="120"><template #default="{ row }">{{ roleLabel(row.role) }}</template></el-table-column>
            <el-table-column prop="weight" label="权重" width="100" />
            <el-table-column label="审核状态" width="110"><template #default="{ row }"><el-tag type="success">{{ row.review_status === 'approved' ? '已通过' : row.review_status }}</el-tag></template></el-table-column>
          </el-table>
        </Panel>

        <Panel v-if="mappingSet.pending_batch" title="待审核批次">
          <el-alert title="已有批次等待审核。审核完成前，当前已生效映射保持不变。" type="warning" show-icon :closable="false" class="state-alert" />
          <el-descriptions :column="3" border><el-descriptions-item label="批次版本">{{ mappingSet.pending_batch.batch_version }}</el-descriptions-item><el-descriptions-item label="基于版本">{{ mappingSet.pending_batch.base_version }}</el-descriptions-item><el-descriptions-item label="提交时间">{{ localDateTime(mappingSet.pending_batch.updated_time) }}</el-descriptions-item></el-descriptions>
          <el-table :data="mappingSet.pending_batch.mappings" class="pending-table">
            <el-table-column prop="knowledge_code" label="知识点编码" min-width="200" />
            <el-table-column label="角色" width="130"><template #default="{ row }">{{ roleLabel(row.role) }}</template></el-table-column>
            <el-table-column prop="weight" label="权重" width="100" />
          </el-table>
          <div v-if="isSuperAdmin" class="review-link"><router-link :to="{ name: 'admin-knowledge-reviews', query: { object_type: 'problem_mapping', status: 'pending', keyword: problem.title } }">前往审核中心 →</router-link></div>
        </Panel>

        <Panel v-if="canSubmit" title="提交新的映射批次">
          <template #header><el-button type="primary" plain @click="beginEditing">{{ editing ? '重新载入当前映射' : mappingSet.mappings.length ? '修改标注' : '开始标注' }}</el-button></template>
          <template v-if="editing">
            <el-alert title="提交后将形成待审核批次；审核通过前不会替换当前映射。" type="info" :closable="false" class="state-alert" />
            <el-alert v-if="validationErrors.length" :title="validationErrors.join('；')" type="error" show-icon :closable="false" class="state-alert" />
            <div v-for="(row, index) in editingMappings" :key="row.key" class="mapping-row">
              <span class="row-number">{{ index + 1 }}</span>
              <el-select v-model="row.knowledge_code" filterable remote reserve-keyword :remote-method="searchPoints" :loading="searching" placeholder="搜索并选择知识点">
                <el-option v-for="item in pointOptions" :key="item.code" :label="`${item.name} (${item.code})`" :value="item.code" />
              </el-select>
              <el-select v-model="row.role" aria-label="角色"><el-option label="主知识点" value="primary" /><el-option label="次要知识点" value="secondary" /><el-option label="前置映射" value="prerequisite" /></el-select>
              <el-input-number v-model="row.weight" :min="0.001" :max="1" :step="0.1" :precision="3" aria-label="权重" />
              <el-button type="danger" link :disabled="editingMappings.length === 1" @click="removeRow(index)">删除</el-button>
            </div>
            <div class="mapping-actions"><el-button :disabled="editingMappings.length >= 20" @click="addRow">添加知识点</el-button><el-button type="primary" :loading="saving" @click="submit">提交审核</el-button></div>
          </template>
          <el-empty v-else description="点击“开始标注”或“修改标注”编辑新的映射批次" :image-size="80" />
        </Panel>
      </template>
    </div>
  </div>
</template>

<script>
  import api from '../../api'
  import { getProblemKnowledgeMappings, listKnowledgePoints, submitProblemKnowledgeMappings } from './knowledgeAdminApi'
  import { errorText, localDateTime } from './knowledgeAdminData'

  let rowNumber = 0
  const row = (values = {}) => ({ key: ++rowNumber, knowledge_code: '', role: 'secondary', weight: 1, ...values })

  export default {
    name: 'ProblemKnowledge',
    data () {
      return {
        loading: false,
        saving: false,
        searching: false,
        error: '',
        problem: {},
        mappingSet: null,
        editing: false,
        editingMappings: [],
        pointOptions: [],
        validationErrors: []
      }
    },
    computed: {
      isSuperAdmin () { return this.$store.getters.isSuperAdmin },
      canSubmit () { return Boolean(this.mappingSet && this.mappingSet.capabilities.includes('submit') && !this.mappingSet.pending_batch) },
      coverageLabel () { return this.mappingSet ? (({ ready: '已标注', in_review: '审核中', unannotated: '未标注' })[this.mappingSet.coverage_status] || this.mappingSet.coverage_status) : '' },
      coverageType () { return !this.mappingSet ? 'info' : this.mappingSet.coverage_status === 'ready' ? 'success' : this.mappingSet.coverage_status === 'in_review' ? 'warning' : 'info' }
    },
    watch: { '$route.params.problemId': 'load' },
    created () { this.load() },
    methods: {
      localDateTime,
      roleLabel (value) { return ({ primary: '主知识点', secondary: '次要知识点', prerequisite: '前置映射' })[value] || value },
      async load () {
        this.loading = true
        this.error = ''
        this.mappingSet = null
        try {
          const [problemResponse, mappings] = await Promise.all([api.getProblem(this.$route.params.problemId), getProblemKnowledgeMappings(this.$route.params.problemId)])
          this.problem = problemResponse.data.data
          this.mappingSet = mappings
        } catch (error) { this.error = error.code ? errorText(error) : '题目信息加载失败，请稍后重试。' } finally { this.loading = false }
      },
      beginEditing () {
        this.editingMappings = this.mappingSet.mappings.length
          ? this.mappingSet.mappings.map(item => row({ knowledge_code: item.knowledge_code, role: item.role, weight: item.weight }))
          : [row({ role: 'primary' })]
        this.pointOptions = this.mappingSet.mappings.map(item => ({ code: item.knowledge_code, name: item.knowledge_name }))
        this.validationErrors = []
        this.editing = true
      },
      addRow () { this.editingMappings.push(row()) },
      removeRow (index) { this.editingMappings.splice(index, 1) },
      async searchPoints (keyword) {
        this.searching = true
        try {
          const data = await listKnowledgePoints({ keyword: keyword || undefined, status: 'active', page_size: 100 })
          const selected = this.pointOptions.filter(item => this.editingMappings.some(row => row.knowledge_code === item.code))
          this.pointOptions = [...selected, ...data.items.filter(item => !selected.some(selectedItem => selectedItem.code === item.code))]
        } catch (error) { this.$error(errorText(error)) } finally { this.searching = false }
      },
      validate () {
        const errors = []
        const codes = this.editingMappings.map(item => item.knowledge_code).filter(Boolean)
        if (this.editingMappings.some(item => !item.knowledge_code)) errors.push('每一行都必须选择知识点')
        if (new Set(codes).size !== codes.length) errors.push('同一知识点不能重复添加')
        if (this.editingMappings.filter(item => item.role === 'primary').length !== 1) errors.push('必须有且只能有一个主知识点')
        if (this.editingMappings.some(item => !(item.weight > 0 && item.weight <= 1))) errors.push('权重必须大于 0 且不超过 1')
        this.validationErrors = errors
        return errors.length === 0
      },
      async submit () {
        if (!this.validate()) return
        this.saving = true
        try {
          await submitProblemKnowledgeMappings(this.$route.params.problemId, { base_version: this.mappingSet.approved_version, mappings: this.editingMappings.map(({ knowledge_code, role, weight }) => ({ knowledge_code, role, weight })) })
          this.$success('题目标注已提交审核')
          this.editing = false
          await this.load()
        } catch (error) { this.$error(errorText(error)); if (error.status === 409) await this.load() } finally { this.saving = false }
      }
    }
  }
</script>

<style scoped lang="less">
  .page-nav { margin-bottom: 12px; }
  .state-alert { margin-bottom: 14px; }
  .problem-tag { margin-right: 6px; }
  .pending-table { margin-top: 15px; }
  .review-link { margin-top: 14px; text-align: right; }
  .mapping-row { display: grid; grid-template-columns: 32px minmax(240px, 1fr) 150px 150px 60px; gap: 12px; align-items: center; margin-bottom: 12px; }
  .row-number { color: #909399; text-align: center; }
  .mapping-row > :deep(.el-select) { width: 100%; }
  .mapping-actions { display: flex; justify-content: space-between; margin-top: 18px; }
  a { color: #409eff; }
</style>
