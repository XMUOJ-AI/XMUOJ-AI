<template>
  <div class="view knowledge-detail-page">
    <div class="page-nav">
      <el-button link type="primary" @click="$router.push({ name: 'admin-knowledge-list' })">← 返回知识点列表</el-button>
      <div v-if="detail" class="page-actions">
        <el-button @click="$router.push({ name: 'admin-knowledge-graph', query: { root_code: point.code, depth: 3 } })">在图谱中查看</el-button>
        <el-button v-if="can('edit')" type="primary" @click="openEdit">编辑基本信息</el-button>
      </div>
    </div>

    <el-alert v-if="error" :title="error" type="error" show-icon :closable="false" class="state-alert">
      <template #default><el-button size="small" @click="load">重新加载</el-button></template>
    </el-alert>

    <div v-loading="loading">
      <template v-if="detail">
        <Panel title="知识点详情">
          <template #header>
            <el-tag :type="statusType(point.status)">{{ labelOf(statusOptions, point.status) }}</el-tag>
          </template>
          <div class="identity">
            <div><h1>{{ point.name }}</h1><code>{{ point.code }}</code></div>
            <div class="identity-tags"><el-tag>{{ labelOf(categories, point.category) }}</el-tag><el-tag type="success">L{{ point.level }}</el-tag></div>
          </div>
          <p class="description">{{ point.description || '暂无描述' }}</p>
          <el-descriptions :column="3" border>
            <el-descriptions-item label="规范名称">{{ point.normalized_name || '—' }}</el-descriptions-item>
            <el-descriptions-item label="版本">{{ point.version }}</el-descriptions-item>
            <el-descriptions-item label="创建人">—</el-descriptions-item>
            <el-descriptions-item label="别名" :span="3">{{ point.aliases && point.aliases.length ? point.aliases.join('、') : '—' }}</el-descriptions-item>
            <el-descriptions-item label="创建时间">{{ localDateTime(point.created_time) }}</el-descriptions-item>
            <el-descriptions-item label="更新时间">{{ localDateTime(point.updated_time) }}</el-descriptions-item>
            <el-descriptions-item label="关联题目">{{ detail.related_problems.total }}</el-descriptions-item>
          </el-descriptions>
          <div v-if="can('change_status') || can('delete_draft')" class="danger-zone">
            <span>状态与删除</span>
            <el-button v-if="point.status === 'draft' && can('change_status')" type="success" plain @click="changeStatus('active')">设为生效</el-button>
            <el-button v-if="point.status === 'active' && can('change_status')" type="warning" plain @click="changeStatus('deprecated')">废弃知识点</el-button>
            <el-button v-if="can('delete_draft')" type="danger" plain @click="openDelete">删除未使用草稿</el-button>
          </div>
        </Panel>

        <Panel title="依赖关系">
          <template #header><el-button v-if="can('request_dependency_change')" type="primary" @click="openCreateDependency">申请新增依赖</el-button></template>
          <el-alert title="正式依赖展示在下方；提交的变更需审核通过后才会影响图谱。" type="info" :closable="false" class="state-alert" />
          <div class="dependency-grid">
            <section>
              <h3>前置依赖（{{ detail.prerequisites.total }}）</h3>
              <el-table :data="detail.prerequisites.items" empty-text="暂无前置依赖" size="small">
                <el-table-column label="知识点" min-width="190"><template #default="{ row }"><router-link :to="{ name: 'admin-knowledge-detail', params: { code: row.code } }">{{ row.name }}</router-link><small>{{ row.code }}</small></template></el-table-column>
                <el-table-column label="类型" width="100"><template #default="{ row }">{{ relationLabel(row.relation_type) }}</template></el-table-column>
                <el-table-column prop="weight" label="权重" width="75" />
                <el-table-column v-if="can('request_dependency_change')" label="操作" width="110"><template #default="{ row }"><el-button link type="primary" @click="openDependencyChange(row, point.code)">变更</el-button><el-button link type="danger" @click="openDependencyDelete(row)">删除</el-button></template></el-table-column>
              </el-table>
            </section>
            <section>
              <h3>后继依赖（{{ detail.dependents.total }}）</h3>
              <el-table :data="detail.dependents.items" empty-text="暂无后继依赖" size="small">
                <el-table-column label="知识点" min-width="190"><template #default="{ row }"><router-link :to="{ name: 'admin-knowledge-detail', params: { code: row.code } }">{{ row.name }}</router-link><small>{{ row.code }}</small></template></el-table-column>
                <el-table-column label="类型" width="100"><template #default="{ row }">{{ relationLabel(row.relation_type) }}</template></el-table-column>
                <el-table-column prop="weight" label="权重" width="75" />
                <el-table-column v-if="can('request_dependency_change')" label="操作" width="110"><template #default="{ row }"><el-button link type="primary" @click="openDependencyChange(row, row.code)">变更</el-button><el-button link type="danger" @click="openDependencyDelete(row)">删除</el-button></template></el-table-column>
              </el-table>
            </section>
          </div>
          <div class="review-link"><router-link v-if="isSuperAdmin" :to="{ name: 'admin-knowledge-reviews', query: { object_type: 'dependency_change', status: 'pending' } }">查看待审核的依赖变更 →</router-link></div>
        </Panel>

        <Panel title="关联题目">
          <el-table :data="detail.related_problems.items" empty-text="暂无关联题目">
            <el-table-column prop="display_id" label="题号" width="120" />
            <el-table-column prop="title" label="标题" min-width="220" />
            <el-table-column label="角色" width="110"><template #default="{ row }">{{ roleLabel(row.role) }}</template></el-table-column>
            <el-table-column prop="weight" label="权重" width="90" />
            <el-table-column label="操作" width="120"><template #default="{ row }"><router-link :to="{ name: 'admin-problem-knowledge', params: { problemId: row.problem_id } }">题目标注</router-link></template></el-table-column>
          </el-table>
        </Panel>
      </template>
    </div>

    <el-dialog v-model="editVisible" title="编辑知识点" width="680px">
      <el-form :model="editing" label-width="100px">
        <el-form-item label="编码"><el-input :model-value="point && point.code" disabled /></el-form-item>
        <el-form-item label="名称"><el-input v-model="editing.name" /></el-form-item>
        <el-form-item label="描述"><el-input v-model="editing.description" type="textarea" :rows="4" /></el-form-item>
        <el-form-item label="分类"><el-select v-model="editing.category"><el-option v-for="item in categories" :key="item[0]" :label="item[1]" :value="item[0]" /></el-select></el-form-item>
        <el-form-item label="层级"><el-input-number v-model="editing.level" :min="1" :max="5" /></el-form-item>
        <el-form-item label="别名"><el-select v-model="editing.aliases" multiple filterable allow-create default-first-option style="width: 100%" /></el-form-item>
      </el-form>
      <template #footer><el-button @click="editVisible = false">取消</el-button><el-button type="primary" :loading="saving" @click="saveEdit">保存</el-button></template>
    </el-dialog>

    <el-dialog v-model="dependencyVisible" :title="dependencyTitle" width="620px">
      <el-form :model="dependency" label-width="110px">
        <template v-if="dependency.operation !== 'delete'">
          <el-form-item label="前置知识点"><el-input v-model="dependency.prerequisite_code" placeholder="知识点编码" /></el-form-item>
          <el-form-item label="后继知识点"><el-input v-model="dependency.dependent_code" placeholder="知识点编码" /></el-form-item>
          <el-form-item label="关系类型"><el-radio-group v-model="dependency.relation_type"><el-radio value="required">必需依赖</el-radio><el-radio value="recommended">推荐依赖</el-radio></el-radio-group></el-form-item>
          <el-form-item label="权重"><el-input-number v-model="dependency.weight" :min="0.001" :max="1" :step="0.1" :precision="3" /></el-form-item>
        </template>
        <el-form-item label="申请原因"><el-input v-model="dependency.reason" type="textarea" :rows="3" placeholder="请说明变更目的，至少 2 个字" /></el-form-item>
      </el-form>
      <template #footer><el-button @click="dependencyVisible = false">取消</el-button><el-button type="primary" :loading="saving" @click="submitDependency">提交审核</el-button></template>
    </el-dialog>
  </div>
</template>

<script>
  import { deleteKnowledgePoint, getKnowledgePoint, submitDependencyChange, updateKnowledgePoint } from './knowledgeAdminApi'
  import { categories, errorText, labelOf, localDateTime, statusOptions, statusType } from './knowledgeAdminData'

  export default {
    name: 'KnowledgeDetail',
    data () {
      return {
        categories,
        statusOptions,
        loading: false,
        saving: false,
        error: '',
        detail: null,
        editVisible: false,
        editing: {},
        dependencyVisible: false,
        dependency: {}
      }
    },
    computed: {
      point () { return this.detail && this.detail.knowledge_point },
      isSuperAdmin () { return this.$store.getters.isSuperAdmin },
      dependencyTitle () { return this.dependency.operation === 'create' ? '申请新增依赖' : this.dependency.operation === 'update' ? '申请变更依赖' : '申请删除依赖' }
    },
    watch: { '$route.params.code': 'load' },
    created () { this.load() },
    methods: {
      labelOf,
      localDateTime,
      statusType,
      can (capability) { return this.detail && this.detail.capabilities.includes(capability) },
      relationLabel (value) { return value === 'required' ? '必需' : '推荐' },
      roleLabel (value) { return ({ primary: '主知识点', secondary: '次要', prerequisite: '前置' })[value] || value },
      async load () {
        this.loading = true
        this.error = ''
        this.detail = null
        try {
          this.detail = await getKnowledgePoint(this.$route.params.code)
          if (this.$route.query.edit === '1' && this.can('edit')) this.openEdit()
        } catch (error) { this.error = errorText(error) } finally { this.loading = false }
      },
      openEdit () {
        this.editing = { name: this.point.name, description: this.point.description, category: this.point.category, level: this.point.level, aliases: [...(this.point.aliases || [])], metadata: { ...(this.point.metadata || {}) } }
        this.editVisible = true
      },
      async saveEdit () {
        if (!this.editing.name.trim() || !this.editing.description.trim()) return this.$error('名称和描述不能为空')
        await this.update({ ...this.editing })
        this.editVisible = false
      },
      async changeStatus (status) {
        const action = status === 'active' ? '设为生效' : '废弃'
        try { await this.$confirm(`确认将“${this.point.name}”${action}？`, `${action}知识点`, { type: 'warning' }) } catch (_) { return }
        await this.update({ status })
      },
      async update (changes) {
        this.saving = true
        try {
          await updateKnowledgePoint(this.point.code, { version: this.point.version, ...changes })
          this.$success('知识点已更新')
          await this.load()
        } catch (error) {
          this.$error(errorText(error))
          if (error.status === 409) await this.load()
        } finally { this.saving = false }
      },
      async openDelete () {
        try {
          const result = await this.$prompt('请输入删除原因（2 至 500 字）', `删除草稿“${this.point.name}”`, { inputType: 'textarea', inputPattern: /^.{2,500}$/s, inputErrorMessage: '删除原因需要 2 至 500 字', type: 'warning' })
          this.saving = true
          await deleteKnowledgePoint(this.point.code, { version: this.point.version, reason: result.value.trim() })
          this.$success('草稿知识点已删除')
          this.$router.push({ name: 'admin-knowledge-list' })
        } catch (error) {
          if (error && error.code) this.$error(errorText(error))
        } finally { this.saving = false }
      },
      openCreateDependency () {
        this.dependency = { operation: 'create', prerequisite_code: this.point.code, dependent_code: '', relation_type: 'required', weight: 1, reason: '' }
        this.dependencyVisible = true
      },
      openDependencyChange (row, dependentCode) {
        this.dependency = { operation: 'update', target_dependency_id: row.dependency_id, base_version: row.version, prerequisite_code: dependentCode === this.point.code ? row.code : this.point.code, dependent_code: dependentCode, relation_type: row.relation_type, weight: row.weight, reason: '' }
        this.dependencyVisible = true
      },
      openDependencyDelete (row) {
        this.dependency = { operation: 'delete', target_dependency_id: row.dependency_id, base_version: row.version, reason: '' }
        this.dependencyVisible = true
      },
      async submitDependency () {
        if (!this.dependency.reason || this.dependency.reason.trim().length < 2) return this.$error('请填写至少 2 个字的申请原因')
        if (this.dependency.operation !== 'delete' && (!this.dependency.prerequisite_code || !this.dependency.dependent_code)) return this.$error('请填写前置和后继知识点编码')
        this.saving = true
        try {
          await submitDependencyChange({ ...this.dependency, reason: this.dependency.reason.trim() })
          this.dependencyVisible = false
          this.$success('依赖变更已提交审核，正式图暂不改变')
        } catch (error) { this.$error(errorText(error)) } finally { this.saving = false }
      }
    }
  }
</script>

<style scoped lang="less">
  .page-nav, .page-actions, .identity, .identity-tags, .danger-zone { display: flex; align-items: center; }
  .page-nav { justify-content: space-between; margin-bottom: 12px; }
  .page-actions, .identity-tags, .danger-zone { gap: 10px; }
  .state-alert { margin-bottom: 14px; }
  .identity { justify-content: space-between; margin-bottom: 16px; }
  .identity h1 { margin: 0 0 6px; font-size: 26px; }
  code, small { display: block; color: #8492a6; font-family: Consolas, monospace; }
  .description { color: #606266; line-height: 1.8; margin-bottom: 20px; }
  .danger-zone { border-top: 1px solid #ebeef5; margin-top: 20px; padding-top: 15px; }
  .danger-zone > span { color: #909399; margin-right: auto; }
  .dependency-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 24px; }
  .dependency-grid h3 { font-size: 15px; font-weight: 500; color: #303133; }
  .review-link { margin-top: 16px; text-align: right; }
  a { color: #409eff; }
  @media (max-width: 1100px) { .dependency-grid { grid-template-columns: 1fr; } }
</style>
