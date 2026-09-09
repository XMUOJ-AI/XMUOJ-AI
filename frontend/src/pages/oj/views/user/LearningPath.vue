<template>
  <section class="learning-path" aria-label="学习路径" aria-live="polite">
    <div v-if="mockEnabled" class="mock-controls">
      <label for="path-scenario">Mock 场景：</label>
      <select id="path-scenario" :value="scenario" @change="changeScenario($event.target.value)">
        <option v-for="item in scenarios" :key="item[0]" :value="item[0]">{{ item[1] }}</option>
      </select>
    </div>
    <div class="heading"><h2>学习路径</h2><Button size="small" :loading="loading" @click="load">更新进度</Button></div>
    <p v-if="loading && !path" class="empty">正在加载学习路径…</p>
    <Alert v-if="error" type="warning" show-icon>{{ error.message }}<span v-if="path">当前显示上次加载的内容。</span><Button v-if="error.action" type="text" @click="handleError(error)">{{ error.label }}</Button></Alert>
    <Alert v-if="pending" type="info" show-icon>有新的学习建议。<Button type="text" @click="acceptPath(pending)">查看新路径</Button></Alert>
    <template v-if="path">
      <div v-if="path.status !== 'ready'" class="empty">
        <h3>{{ stateTitle }}</h3><p>{{ path.message }}</p>
        <p v-if="path.status === 'generating'">页面会自动检查生成进度。</p>
        <router-link v-else :to="{name: 'problem-list'}">去公共题库练习 →</router-link>
      </div>
      <template v-else>
        <p class="muted">根据截至 {{ formatDate(path.based_on_until) }} 的练习记录生成 · {{ {starter: '入门路径', personalized: '个性化路径'}[path.kind] || '学习路径' }}</p>
        <h3 class="summary">{{ path.summary }}</h3>
        <div class="focus"><Tag v-for="(point, index) in path.focus_points" :key="index">{{ point.label }} · {{ assessmentLabel(point.assessment) }}</Tag></div>
        <Button v-if="path.evidence.length" type="text" size="small" @click="showEvidence = !showEvidence">{{ showEvidence ? '收起分析依据' : '查看分析依据' }}</Button>
        <ul v-if="showEvidence" class="evidence"><li v-for="(item, index) in path.evidence" :key="index">{{ item.text }}</li></ul>
        <div class="progress">已完成 {{ completed }} / {{ path.steps.length }} 步 <span v-if="!path.next_step_id">· {{ completed === path.steps.length ? '本轮训练已完成' : '暂无可开始的题目' }}</span></div>
        <h3>完整学习路径</h3>
        <div v-for="step in path.steps" :key="step.step_id" class="step" :class="{current: step.step_id === path.next_step_id}">
          <button class="step-heading" :aria-expanded="selected === step.step_id ? 'true' : 'false'" @click="selectStep(step.step_id)">
            <span class="number">{{ step.status === 'completed' ? '✓' : step.order }}</span>
            <span>{{ step.title }} <small v-if="step.step_id === path.next_step_id">当前建议</small></span>
            <span class="step-status">{{ statusLabel(step.status) }} {{ selected === step.step_id ? '−' : '+' }}</span>
          </button>
          <div v-if="selected === step.step_id" class="step-body">
            <p>训练目标：{{ step.objective }}</p>
            <p v-if="!step.problems.length" class="muted">此步骤暂无可用练习题。</p>
            <div v-for="problem in step.problems" :key="problem.problem_id" class="practice">
              <div><strong>{{ problem.display_id }} · {{ problem.title }}</strong><p class="muted">{{ statusLabel(problem.status) }}</p></div>
              <Button :type="problem.problem_id === path.next_problem_id ? 'primary' : 'default'" :disabled="blocked || problem.availability !== 'available'" @click="start(step, problem)">{{ problem.status === 'completed' ? '再次练习' : '开始练习' }}</Button>
              <p v-if="problem.availability !== 'available'" class="unavailable">{{ problem.unavailable_reason || '题目暂不可用，请练习其他题目' }}</p>
            </div>
            <Button v-if="step.explanation_available" type="text" @click="explain(step)">{{ explanations[step.step_id] && explanations[step.step_id].open ? '收起解释' : '为什么推荐' }}</Button>
            <p v-else class="muted">推荐解释暂不可用，仍可继续练习。</p>
            <div v-if="explanations[step.step_id] && explanations[step.step_id].open" class="explanation">
              <p v-if="explanations[step.step_id].status === 'loading'">正在解释推荐依据…</p>
              <p v-else-if="explanations[step.step_id].status === 'ready'">{{ explanations[step.step_id].text }}</p>
              <p v-else>{{ explanations[step.step_id].error.message }}<Button v-if="explanations[step.step_id].error.action" type="text" @click="handleError(explanations[step.step_id].error, step)">{{ explanations[step.step_id].error.label }}</Button></p>
            </div>
          </div>
        </div>
      </template>
    </template>
  </section>
</template>
<script>
  import api from '@oj/api'
  import time from '@/utils/time'
  import { id, normalizePath, statusLabel, assessmentLabel, errorFeedback } from './learningPathData'

  export default {
    data () {
      return {
        path: null,
        pending: null,
        loading: false,
        error: null,
        showEvidence: false,
        explanations: {},
        timer: null,
        requestId: 0,
        mockEnabled: process.env.LEARNING_PATH_MOCK === true,
        scenarios: [['ready', '正常路径'], ['starter', '入门路径'], ['insufficient_data', '数据不足'], ['empty', '暂无推荐'], ['generating', '生成中'], ['error', '加载失败'], ['explanation_error', '解释失败'], ['unavailable', '题目不可用'], ['judging', '判题中'], ['new_version', '新版本提醒'], ['compatibility', '扩展字段与多题'], ['invalid_data', '无效推荐引用'], ['expired', '旧版本失效'], ['unauthenticated', '登录过期']]
      }
    },
    computed: {
      scenario () { return this.mockEnabled ? (this.$route.query.mock_path || 'ready') : undefined },
      routeIdentity () { return JSON.stringify([id(this.$route.query.path), id(this.$route.query.revision), this.scenario]) },
      blocked () { return this.error && ['login', 'latest', null].includes(this.error.action) },
      selected () {
        if (!this.path || !this.path.steps) return null
        const id = this.$route.query.step
        if (id === 'none') return null
        return this.path.steps.some(step => step.step_id === id) ? id : (this.path.next_step_id || (this.path.steps[0] || {}).step_id)
      },
      completed () { return this.path.steps.filter(step => step.status === 'completed').length },
      stateTitle () {
        return { generating: '正在整理你的练习路径', insufficient_data: '练习记录还不够', empty: '暂无可用推荐' }[this.path.status] || '路径暂不可用'
      }
    },
    watch: {
      routeIdentity () {
        this.invalidate()
        this.path = null
        this.pending = null
        this.explanations = {}
        this.load()
      }
    },
    mounted () { this.load() },
    beforeDestroy () { this.invalidate() },
    methods: {
      formatDate (date) { return date ? time.utcToLocal(date, 'YYYY-MM-DD HH:mm') : '未知时间' },
      statusLabel,
      assessmentLabel,
      invalidate () {
        clearTimeout(this.timer)
        this.requestId++
        this.loading = false
      },
      // Callbacks also work with the historical Vue Router 3.0 installation.
      replaceRoute (query) {
        return new Promise((resolve, reject) => this.$router.replace({ query }, resolve, reject))
      },
      handleError (error, step) {
        if (error.action === 'login') {
          this.$store.dispatch('changeModalStatus', { mode: 'login', visible: true })
        } else if (error.action === 'latest') {
          this.invalidate()
          const query = { ...this.$route.query }
          delete query.path
          delete query.revision
          delete query.step
          if (this.$route.query.path || this.$route.query.revision) this.replaceRoute(query).catch(() => {})
          else { this.path = null; this.explanations = {}; this.load() }
        } else if (error.action === 'retry') {
          if (step) this.explain(step, true)
          else this.load()
        }
      },
      changeScenario (value) {
        this.$router.replace({ query: { ...this.$route.query, mock_path: value } })
      },
      selectStep (id) {
        const selected = this.selected === id ? 'none' : id
        this.$router.replace({ query: { ...this.$route.query, step: selected } })
      },
      async load () {
        clearTimeout(this.timer)
        const requestId = ++this.requestId
        const routeIdentity = this.routeIdentity
        this.loading = true
        this.error = null
        try {
          const requestedPath = id(this.$route.query.path) || (this.path && this.path.path_id)
          const requestedRevision = id(this.$route.query.revision) || (this.path && this.path.revision)
          const res = await api.getLearningPath({ mock_path: this.scenario, path_id: requestedPath, revision: requestedRevision })
          if (requestId !== this.requestId || routeIdentity !== this.routeIdentity) return
          const data = normalizePath(res.data.data)
          if (data.status === 'ready' && ((requestedPath && data.path_id !== requestedPath) || (requestedRevision && data.revision !== requestedRevision))) {
            throw Object.assign(new Error('Version mismatch'), { code: 'version_mismatch' })
          }
          this.pending = null
          if (data.latest_path) {
            try {
              const latest = normalizePath(data.latest_path)
              if (latest.status === 'ready' && (latest.path_id !== data.path_id || latest.revision !== data.revision)) this.pending = latest
            } catch (e) { /* An invalid new recommendation must not hide the current path. */ }
          }
          this.applyPath(data)
          if (data.status === 'generating') this.timer = setTimeout(this.load, Math.max(3000, (Number(data.retry_after_seconds) || 10) * 1000))
        } catch (e) {
          if (requestId === this.requestId) {
            this.error = errorFeedback(e)
            if (this.error.action === 'login' || this.error.action === null) { this.path = null; this.pending = null; this.explanations = {} }
          }
        } finally {
          if (requestId === this.requestId) this.loading = false
        }
      },
      applyPath (data) {
        if (!this.path || this.path.path_id !== data.path_id || this.path.revision !== data.revision) this.explanations = {}
        this.path = data
      },
      acceptPath (data) {
        this.invalidate()
        this.replaceRoute({ ...this.$route.query, path: data.path_id, revision: data.revision, step: data.next_step_id }).catch(() => {})
      },
      async start (step, problem) {
        if (this.blocked || problem.availability !== 'available') return
        const context = problem.context
        const query = { from: 'learning-path', step: step.step_id, path: this.path.path_id, revision: String(this.path.revision) }
        if (this.scenario) query.mock_path = this.scenario
        const origin = { ...this.$route.query, step: step.step_id, path: this.path.path_id, revision: String(this.path.revision) }
        if (Object.keys(origin).some(key => origin[key] !== this.$route.query[key])) {
          try { await this.replaceRoute(origin) } catch (e) { return }
        }
        this.$router.push({ name: context.type === 'contest' ? 'contest-problem-details' : 'problem-details', params: { problemID: problem.display_id, contestID: context.contest_id }, query }, () => {}, () => {})
      },
      async explain (step, retry = false) {
        const previous = this.explanations[step.step_id]
        if (previous && !retry) { previous.open = !previous.open; return }
        const entry = { open: true, status: 'loading', text: '', error: null }
        const pathId = this.path.path_id
        const revision = this.path.revision
        this.$set(this.explanations, step.step_id, entry)
        try {
          const res = await api.explainLearningStep({ path_id: pathId, revision, step_id: step.step_id, mock_path: this.scenario })
          const data = res.data.data
          if (this.explanations[step.step_id] !== entry) return
          if (id(data.path_id) !== pathId || id(data.revision) !== revision || id(data.step_id) !== step.step_id) throw Object.assign(new Error('Version mismatch'), { code: 'version_mismatch' })
          if (data.status !== 'ready' || typeof data.text !== 'string' || !data.text) throw new Error('Explanation unavailable')
          entry.status = 'ready'
          entry.text = data.text
        } catch (e) {
          if (this.explanations[step.step_id] !== entry) return
          entry.status = 'error'
          entry.error = errorFeedback(e)
        }
      }
    }
  }
</script>
<style lang="less" scoped>
  .learning-path { padding: 24px; color: #303b4b; }
  .heading { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }
  h2 { font-size: 21px; } h3 { font-size: 16px; }
  .muted { color: #687587; font-size: 12px; margin: 7px 0; }
  .summary { margin: 20px 0 12px; }
  .focus { margin-bottom: 6px; }
  .evidence { padding: 12px 24px; background: #f6f8fb; line-height: 1.9; }
  .progress { margin: 22px 0 12px; color: #536880; }
  .step { border: 1px solid #e2e7ee; border-radius: 8px; margin-top: 12px; overflow: hidden; }
  .current { border-color: #a7c9ed; background: #f8fbff; }
  .step-heading { width: 100%; display: flex; align-items: center; text-align: left; padding: 16px; background: transparent; border: 0; cursor: pointer; color: inherit; font: inherit; }
  .number { border-radius: 50%; background: #e6eef8; padding: 4px 9px; margin-right: 12px; }
  small { color: #236db5; margin-left: 8px; }
  .step-status { margin-left: auto; white-space: nowrap; color: #687587; font-size: 12px; }
  .step-body { padding: 0 20px 20px; line-height: 1.8; }
  .practice { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 10px; padding: 16px 0; border-bottom: 1px solid #e6ecf3; }
  .unavailable { flex-basis: 100%; color: #916326; }
  .explanation { padding: 14px; background: #edf3fa; border-radius: 6px; white-space: pre-line; }
  .empty { padding: 36px 0; text-align: center; line-height: 2.2; }
  .mock-controls { padding: 10px; background: #fff7e6; margin-bottom: 20px; font-size: 12px; }
  select { padding: 4px; max-width: 100%; }
  @media (max-width: 600px) { .learning-path { padding: 14px; } .step-heading { padding: 12px; } small { display: block; } }
</style>
