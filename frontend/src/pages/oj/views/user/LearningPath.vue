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
    <Alert v-if="error" type="warning" show-icon>学习路径加载失败{{ path ? '，保留上次内容' : '' }}。<a @click="load">重试</a></Alert>
    <Alert v-if="pending" type="info" show-icon>有新的学习建议。<a @click="acceptPath(pending)">查看新路径</a></Alert>
    <template v-if="path">
      <div v-if="path.status !== 'ready'" class="empty">
        <h3>{{ stateTitle }}</h3><p>{{ path.message }}</p>
        <p v-if="path.status === 'generating'">页面会自动检查生成进度。</p>
        <router-link v-else :to="{name: 'problem-list'}">去公共题库练习 →</router-link>
      </div>
      <template v-else>
        <p class="muted">根据截至 {{ formatDate(path.based_on_until) }} 的练习记录生成 · {{ path.kind === 'starter' ? '入门路径' : '个性化路径' }}</p>
        <h3 class="summary">{{ path.summary }}</h3>
        <div class="focus"><Tag v-for="point in path.focus_points" :key="point.knowledge_id">{{ point.label }} · {{ point.assessment === 'insufficient' ? '待了解' : '建议巩固' }}</Tag></div>
        <Button type="text" size="small" @click="showEvidence = !showEvidence">{{ showEvidence ? '收起分析依据' : '查看分析依据' }}</Button>
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
            <div v-for="problem in step.problems" :key="problem.problem_id" class="practice">
              <div><strong>{{ problem.display_id }} · {{ problem.title }}</strong><p class="muted">{{ statusLabel(problem.status) }}</p></div>
              <Button :type="problem.problem_id === path.next_problem_id ? 'primary' : 'default'" :disabled="problem.availability !== 'available'" @click="start(step, problem)">{{ problem.status === 'completed' ? '再次练习' : '开始练习' }}</Button>
              <p v-if="problem.availability !== 'available'" class="unavailable">{{ problem.unavailable_reason || '题目暂不可用，请练习其他题目' }}</p>
            </div>
            <Button v-if="step.explanation_available" type="text" @click="explain(step)">{{ explanations[step.step_id] && explanations[step.step_id].open ? '收起解释' : '为什么推荐' }}</Button>
            <p v-else class="muted">推荐解释暂不可用，仍可继续练习。</p>
            <div v-if="explanations[step.step_id] && explanations[step.step_id].open" class="explanation">
              <p v-if="explanations[step.step_id].status === 'loading'">正在解释推荐依据…</p>
              <p v-else-if="explanations[step.step_id].status === 'ready'">{{ explanations[step.step_id].text }}</p>
              <p v-else>解释暂时不可用，不影响练习。<a @click="explain(step, true)">重试</a></p>
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

  export default {
    data () {
      return {
        path: null,
        pending: null,
        loading: false,
        error: false,
        showEvidence: false,
        explanations: {},
        timer: null,
        requestId: 0,
        mockEnabled: process.env.LEARNING_PATH_MOCK === true,
        scenarios: [['ready', '正常路径'], ['starter', '入门路径'], ['insufficient_data', '数据不足'], ['empty', '暂无推荐'], ['generating', '生成中'], ['error', '加载失败'], ['explanation_error', '解释失败'], ['unavailable', '题目不可用'], ['judging', '判题中'], ['new_version', '新版本提醒']]
      }
    },
    computed: {
      scenario () { return this.mockEnabled ? (this.$route.query.mock_path || 'ready') : undefined },
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
      scenario () { this.explanations = {}; this.load() }
    },
    mounted () { this.load() },
    beforeDestroy () { clearTimeout(this.timer); this.requestId++ },
    methods: {
      formatDate (date) { return date ? time.utcToLocal(date, 'YYYY-MM-DD HH:mm') : '未知时间' },
      statusLabel (status) { return { completed: '已完成', judging: '判题中', pending: '未完成' }[status] || '未完成' },
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
        this.loading = true
        this.error = false
        try {
          const res = await api.getLearningPath({ mock_path: this.scenario, path_id: this.path ? this.path.path_id : this.$route.query.path, revision: this.path ? this.path.revision : this.$route.query.revision })
          if (requestId !== this.requestId) return
          const data = res.data.data
          if (data.status === 'ready' && (!Array.isArray(data.steps) || !data.path_id || data.revision === undefined)) throw new Error('Invalid path')
          this.pending = data.latest_path || null
          this.applyPath(data)
          if (data.status === 'generating') this.timer = setTimeout(this.load, Math.max(3000, (Number(data.retry_after_seconds) || 10) * 1000))
        } catch (e) {
          if (requestId === this.requestId) this.error = true
        } finally {
          if (requestId === this.requestId) this.loading = false
        }
      },
      applyPath (data) {
        if (!this.path || this.path.path_id !== data.path_id || this.path.revision !== data.revision) this.explanations = {}
        this.path = data
      },
      acceptPath (data) {
        this.applyPath(data)
        this.pending = null
        this.$router.replace({ query: { ...this.$route.query, path: data.path_id, revision: String(data.revision), step: data.next_step_id } })
      },
      async start (step, problem) {
        const context = problem.context || { type: 'public' }
        const query = { from: 'learning-path', step: step.step_id, path: this.path.path_id, revision: String(this.path.revision) }
        if (this.scenario) query.mock_path = this.scenario
        const origin = { ...this.$route.query, step: step.step_id, path: this.path.path_id, revision: String(this.path.revision) }
        if (Object.keys(origin).some(key => origin[key] !== this.$route.query[key])) {
          await this.$router.replace({ name: 'user-home', query: origin })
        }
        this.$router.push({ name: context.type === 'contest' ? 'contest-problem-details' : 'problem-details', params: { problemID: problem.display_id, contestID: context.contest_id }, query })
      },
      async explain (step, retry = false) {
        const previous = this.explanations[step.step_id]
        if (previous && !retry) { previous.open = !previous.open; return }
        const entry = { open: true, status: 'loading', text: '' }
        this.$set(this.explanations, step.step_id, entry)
        try {
          const res = await api.explainLearningStep({ path_id: this.path.path_id, revision: this.path.revision, step_id: step.step_id, mock_path: this.scenario })
          const data = res.data.data
          const matches = data.path_id === this.path.path_id && data.revision === this.path.revision && data.step_id === step.step_id
          entry.status = matches && data.status === 'ready' && data.text ? 'ready' : 'error'
          entry.text = data.text || ''
        } catch (e) { entry.status = 'error' }
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
