<template>
  <div class="view knowledge-admin-page">
    <Panel title="知识点管理">
      <template #header>
        <div class="header-actions">
          <el-button @click="$router.push({ name: 'admin-knowledge-graph' })">查看知识图谱</el-button>
          <el-button v-if="isSuperAdmin" type="primary" @click="openCreate">新建知识点</el-button>
        </div>
      </template>

      <el-form class="filters" inline @submit.prevent>
        <el-form-item label="关键词">
          <el-input v-model="draft.keyword" clearable placeholder="编码、名称或别名" @keyup.enter="applyFilters" />
        </el-form-item>
        <el-form-item label="分类">
          <el-select v-model="draft.category" clearable placeholder="全部分类">
            <el-option v-for="item in categories" :key="item[0]" :label="item[1]" :value="item[0]" />
          </el-select>
        </el-form-item>
        <el-form-item label="层级">
          <el-select v-model="draft.level" clearable placeholder="全部层级">
            <el-option v-for="level in 5" :key="level" :label="`L${level}`" :value="String(level)" />
          </el-select>
        </el-form-item>
        <el-form-item label="状态">
          <el-select v-model="draft.status" clearable placeholder="全部状态">
            <el-option v-for="item in statusOptions" :key="item[0]" :label="item[1]" :value="item[0]" />
          </el-select>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" @click="applyFilters">查询</el-button>
          <el-button @click="resetFilters">重置</el-button>
        </el-form-item>
      </el-form>

      <el-alert v-if="error" :title="error" type="error" show-icon :closable="false" class="state-alert" />
      <el-table v-loading="loading" :data="items" empty-text="当前筛选条件下没有知识点" stripe>
        <el-table-column prop="code" label="编码" min-width="170"><template #default="{ row }"><code>{{ row.code }}</code></template></el-table-column>
        <el-table-column prop="name" label="名称" min-width="180">
          <template #default="{ row }"><router-link :to="{ name: 'admin-knowledge-detail', params: { code: row.code } }">{{ row.name }}</router-link></template>
        </el-table-column>
        <el-table-column label="分类" width="120"><template #default="{ row }">{{ labelOf(categories, row.category) }}</template></el-table-column>
        <el-table-column label="层级" width="80"><template #default="{ row }">L{{ row.level }}</template></el-table-column>
        <el-table-column label="状态" width="100"><template #default="{ row }"><el-tag :type="statusType(row.status)">{{ labelOf(statusOptions, row.status) }}</el-tag></template></el-table-column>
        <el-table-column prop="related_problem_count" label="关联题目" width="100" align="center" />
        <el-table-column prop="prerequisite_count" label="前置" width="80" align="center" />
        <el-table-column prop="dependent_count" label="后继" width="80" align="center" />
        <el-table-column label="更新时间" min-width="170"><template #default="{ row }">{{ localDateTime(row.updated_time) }}</template></el-table-column>
        <el-table-column label="操作" width="190" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="$router.push({ name: 'admin-knowledge-detail', params: { code: row.code } })">查看</el-button>
            <el-button link type="primary" @click="$router.push({ name: 'admin-knowledge-graph', query: { root_code: row.code, depth: 3 } })">图谱</el-button>
            <el-button v-if="isSuperAdmin" link type="primary" @click="$router.push({ name: 'admin-knowledge-detail', params: { code: row.code }, query: { edit: '1' } })">编辑</el-button>
          </template>
        </el-table-column>
      </el-table>

      <div class="pagination-row">
        <el-pagination
          v-model:current-page="page"
          v-model:page-size="pageSize"
          :page-sizes="[10, 20, 50, 100]"
          :total="total"
          layout="total, sizes, prev, pager, next"
          @current-change="changePage"
          @size-change="changePageSize" />
      </div>
    </Panel>

    <el-dialog v-model="createVisible" title="新建知识点" width="680px" @closed="resetCreate">
      <el-form ref="createForm" :model="creating" :rules="rules" label-width="100px">
        <el-form-item label="编码" prop="code"><el-input v-model="creating.code" placeholder="小写字母开头，可使用数字和下划线" /></el-form-item>
        <el-form-item label="名称" prop="name"><el-input v-model="creating.name" /></el-form-item>
        <el-form-item label="描述" prop="description"><el-input v-model="creating.description" type="textarea" :rows="4" /></el-form-item>
        <el-form-item label="分类" prop="category"><el-select v-model="creating.category"><el-option v-for="item in categories" :key="item[0]" :label="item[1]" :value="item[0]" /></el-select></el-form-item>
        <el-form-item label="层级" prop="level"><el-input-number v-model="creating.level" :min="1" :max="5" /></el-form-item>
        <el-form-item label="别名"><el-select v-model="creating.aliases" multiple filterable allow-create default-first-option placeholder="输入后回车，可添加多个" style="width: 100%" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="submitCreate">创建</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script>
  import { createKnowledgePoint, listKnowledgePoints } from './knowledgeAdminApi'
  import { categories, compactParams, errorText, labelOf, localDateTime, statusOptions, statusType } from './knowledgeAdminData'

  const emptyPoint = () => ({ code: '', name: '', description: '', category: 'basic', level: 1, aliases: [], metadata: {} })

  export default {
    name: 'KnowledgeList',
    data () {
      return {
        categories,
        statusOptions,
        loading: false,
        saving: false,
        error: '',
        items: [],
        total: 0,
        page: 1,
        pageSize: 20,
        draft: { keyword: '', category: '', level: '', status: '' },
        createVisible: false,
        creating: emptyPoint(),
        rules: {
          code: [{ required: true, message: '请输入编码', trigger: 'blur' }, { pattern: /^[a-z][a-z0-9_]{0,63}$/, message: '编码格式不正确', trigger: 'blur' }],
          name: [{ required: true, message: '请输入名称', trigger: 'blur' }],
          description: [{ required: true, message: '请输入描述', trigger: 'blur' }],
          category: [{ required: true, message: '请选择分类', trigger: 'change' }],
          level: [{ required: true, message: '请选择层级', trigger: 'change' }]
        }
      }
    },
    computed: {
      isSuperAdmin () { return this.$store.getters.isSuperAdmin }
    },
    watch: {
      '$route.query': { handler () { this.restoreFromRoute(); this.load() }, deep: true }
    },
    created () { this.restoreFromRoute(); this.load() },
    methods: {
      labelOf,
      localDateTime,
      statusType,
      restoreFromRoute () {
        const query = this.$route.query
        this.page = Math.max(1, Number(query.page) || 1)
        this.pageSize = [10, 20, 50, 100].includes(Number(query.page_size)) ? Number(query.page_size) : 20
        this.draft = { keyword: query.keyword || '', category: query.category || '', level: query.level || '', status: query.status || '' }
      },
      routeQuery (overrides = {}) {
        return compactParams({ ...this.draft, page: this.page > 1 ? this.page : '', page_size: this.pageSize !== 20 ? this.pageSize : '', ...overrides })
      },
      async load () {
        this.loading = true
        this.error = ''
        try {
          const data = await listKnowledgePoints({ ...compactParams(this.draft), page: this.page, page_size: this.pageSize })
          this.items = data.items
          this.total = data.total
        } catch (error) {
          this.items = []
          this.total = 0
          this.error = errorText(error)
        } finally { this.loading = false }
      },
      applyFilters () { this.$router.push({ name: 'admin-knowledge-list', query: this.routeQuery({ page: '' }) }) },
      resetFilters () { this.draft = { keyword: '', category: '', level: '', status: '' }; this.$router.push({ name: 'admin-knowledge-list' }) },
      changePage (page) { this.$router.push({ name: 'admin-knowledge-list', query: this.routeQuery({ page: page > 1 ? page : '' }) }) },
      changePageSize (size) { this.$router.push({ name: 'admin-knowledge-list', query: this.routeQuery({ page: '', page_size: size !== 20 ? size : '' }) }) },
      openCreate () { this.creating = emptyPoint(); this.createVisible = true },
      resetCreate () { this.creating = emptyPoint(); this.$refs.createForm && this.$refs.createForm.clearValidate() },
      async submitCreate () {
        const valid = await this.$refs.createForm.validate().catch(() => false)
        if (!valid) return
        this.saving = true
        try {
          const point = await createKnowledgePoint(this.creating)
          this.createVisible = false
          this.$success('知识点已创建')
          this.$router.push({ name: 'admin-knowledge-detail', params: { code: point.code } })
        } catch (error) { this.$error(errorText(error)) } finally { this.saving = false }
      }
    }
  }
</script>

<style scoped lang="less">
  .header-actions, .pagination-row { display: flex; justify-content: flex-end; gap: 10px; }
  .filters { display: flex; flex-wrap: wrap; align-items: center; gap: 0 8px; margin-bottom: 6px; }
  .filters :deep(.el-input), .filters :deep(.el-select) { width: 190px; }
  .state-alert { margin-bottom: 14px; }
  .pagination-row { margin-top: 18px; }
  code { color: #44546a; font-family: Consolas, monospace; }
  a { color: #409eff; }
</style>
