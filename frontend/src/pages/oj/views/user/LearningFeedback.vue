<template>
  <section class="learning-feedback" aria-label="学习反馈" aria-live="polite">
    <div v-if="mockEnabled" class="mock-controls">
      <label for="feedback-scenario">Mock 场景：</label>
      <select id="feedback-scenario" :value="scenario" @change="changeScenario($event.target.value)">
        <option v-for="item in scenarios" :key="item[0]" :value="item[0]">{{ item[1] }}</option>
      </select>
      <p>模拟学习记录与资料，仅供页面预览。</p>
    </div>
    <div class="heading"><h2>学习反馈</h2><Button size="small" :disabled="working" @click="load">刷新记录</Button></div>
    <p class="muted intro">回顾近期练习，结合知识点资料，整理下一步复习建议。</p>
    <p v-if="loading" class="empty">正在读取近期学习记录…</p>
    <Alert v-if="error" type="warning" show-icon>
      {{ error.message }}
      <Button v-if="error.action" type="text" :disabled="working" @click="handleError">{{ error.action === 'login' ? '重新登录' : '重试' }}</Button>
    </Alert>
    <template v-if="basis">
      <div v-if="basis.status !== 'ready'" class="empty">
        <h3>{{ {empty: '还没有近期学习记录', disabled: '学习反馈暂未开放', unknown: '学习反馈状态待确认'}[basis.status] }}</h3>
        <p>{{ basis.reason || '可以继续练习，稍后再查看。' }}</p>
        <router-link :to="{name: 'problem-list'}">去公共题库 →</router-link>
      </div>
      <template v-else>
        <div class="record-summary">
          <h3>本次反馈的学习依据</h3>
          <p class="muted">{{ formatDate(basis.range.start) }} 至 {{ formatDate(basis.range.end) }} · {{ basis.submission_count }} 次提交</p>
          <Button type="text" size="small" @click="showEvidence = !showEvidence">{{ showEvidence ? '收起记录' : '查看学习记录' }}</Button>
          <ul v-if="showEvidence" class="evidence"><li v-for="item in basis.evidence" :key="item.id"><span class="muted">{{ formatDate(item.occurred_at) }}</span> · {{ item.text }}</li></ul>
        </div>
        <div v-if="!feedback && !generating" class="generate-intro">
          <p>点击后生成知识点回顾与复习建议。一次通过不代表已经掌握，记录不足时会明确说明。</p>
          <p v-if="!summary.can_generate" class="muted">{{ summary.reason || '当前暂不支持生成学习反馈。' }}</p>
        </div>
        <div v-if="generating || (feedback && feedback.status === 'generating')" class="empty">
          <h3>正在整理学习反馈</h3>
          <p>{{ pollingPaused ? '生成时间较长，可以稍后检查结果。' : '正在结合练习记录与可用资料，请稍候…' }}</p>
          <Button v-if="pollingPaused" :disabled="working" @click="checkResult">检查结果</Button>
        </div>
        <template v-else-if="feedback">
          <template v-if="feedback.status === 'ready'">
            <h3 class="section-title">近期回顾</h3><p class="overview">{{ feedback.overview }}</p>
            <h3 class="section-title">知识点反馈</h3>
            <div v-for="point in feedback.points" :key="point.id" class="point">
              <div><strong>{{ point.label }}</strong><Tag>{{ assessmentLabel(point.assessment) }}</Tag></div>
              <p>{{ point.observation }}</p><p v-if="point.source_ids.length" class="muted">参考资料：{{ referenceLabels(point.source_ids) }}</p>
            </div>
            <h3 class="section-title">接下来可以这样复习</h3>
            <ol class="suggestions"><li v-for="item in feedback.suggestions" :key="item.id">{{ item.action }}<p v-if="item.source_ids.length" class="muted">参考资料：{{ referenceLabels(item.source_ids) }}</p></li></ol>
            <h3 class="section-title">参考资料</h3>
            <p v-if="!feedback.sources.length" class="muted">暂未返回可核对的资料引用。</p>
            <div v-for="source in feedback.sources" :key="source.id" class="source">
              <strong>{{ source.title }}</strong><span v-if="source.version" class="muted"> · {{ source.version }}</span>
              <Button v-if="source.available" type="text" size="small" :aria-expanded="openSource === source.id ? 'true' : 'false'" @click="openSource = openSource === source.id ? null : source.id">{{ openSource === source.id ? '收起摘录' : '查看摘录' }}</Button>
              <p v-if="!source.available" class="muted">{{ source.reason }}</p>
              <blockquote v-else-if="openSource === source.id">{{ source.excerpt }}</blockquote>
            </div>
            <p class="muted footnote">反馈用于辅助复习，请结合原始记录与资料核对。</p>
          </template>
          <div v-else class="empty">
            <h3>{{ {insufficient: '暂时没有足够依据', failed: '本次生成未完成', disabled: '学习反馈暂未开放', unknown: '反馈状态待确认'}[feedback.status] }}</h3>
            <p>{{ feedback.message || '可以继续练习，稍后再查看。' }}</p>
          </div>
        </template>
        <div class="actions">
          <Button v-if="canGenerate" type="primary" :loading="generating" :disabled="working" @click="generate">{{ feedback ? (feedback.status === 'failed' ? '重新生成' : '更新学习反馈') : '生成学习反馈' }}</Button>
          <router-link :to="{name: 'user-home', query: pathQuery}">查看学习路径 →</router-link>
        </div>
      </template>
    </template>
  </section>
</template>
<script>
  import api from './learningFeedbackApi'
  import time from '@/utils/time'
  import { id, normalizeSummary, normalizeFeedback, assessmentLabel, errorFeedback } from './learningFeedbackData'

  export default {
    data () {
      return {
        summary: null,
        feedback: null,
        error: null,
        failedOperation: 'load',
        loading: false,
        generating: false,
        checking: false,
        pollingPaused: false,
        requestId: 0,
        timer: null,
        polls: 0,
        showEvidence: false,
        openSource: null,
        mockEnabled: process.env.AI_FEATURES_MOCK === true,
        scenarios: [['ready', '正常反馈'], ['empty', '无记录'], ['generating', '生成中'], ['insufficient', '依据不足'], ['failed', '生成失败'], ['retry', '失败后重试成功'], ['disabled', '禁用'], ['unauthenticated', '登录过期'], ['busy', '服务繁忙'], ['unavailable', '引用不可用'], ['unknown', '未知状态'], ['invalid', '身份不匹配'], ['load_error', '摘要加载失败']]
      }
    },
    computed: {
      userId () { return id(this.$store.getters.user.id) },
      scenario () { return this.mockEnabled ? (typeof this.$route.query.mock_feedback === 'string' ? this.$route.query.mock_feedback : 'ready') : undefined },
      identity () { return JSON.stringify([this.userId, this.$route.query.username, this.scenario]) },
      working () { return this.loading || this.generating || this.checking },
      basis () { return (this.feedback && this.feedback.basis) || this.summary },
      canGenerate () {
        return this.summary && this.summary.can_generate && (!this.error || this.error.action === 'retry') && (!this.feedback || ['ready', 'failed', 'insufficient'].includes(this.feedback.status))
      },
      pathQuery () { return { ...this.$route.query, tab: 'learning-path' } }
    },
    watch: { identity () { this.reset(); this.load() } },
    mounted () { this.load() },
    beforeDestroy () { this.reset() },
    methods: {
      assessmentLabel,
      formatDate (value) { return value ? time.utcToLocal(value, 'YYYY-MM-DD HH:mm') : '未知时间' },
      referenceLabels (ids) { return ids.map(key => this.feedback.sources.find(source => source.id === key).title).join('、') },
      reset () {
        clearTimeout(this.timer)
        this.requestId++
        this.summary = null
        this.feedback = null
        this.error = null
        this.loading = this.generating = this.checking = this.pollingPaused = false
        this.showEvidence = false
        this.openSource = null
        this.polls = 0
      },
      changeScenario (value) { this.$router.replace({ query: { ...this.$route.query, mock_feedback: value } }) },
      current (token, identity) { return this.requestId === token && this.identity === identity },
      fail (error, operation) {
        clearTimeout(this.timer)
        this.error = errorFeedback(error)
        this.failedOperation = operation
        if (this.error.action !== 'retry') { this.summary = null; this.feedback = null }
        if (operation === 'check') this.pollingPaused = true
      },
      async load () {
        if (this.working) return
        this.reset()
        if (!this.userId) { this.fail({ code: 'not_authenticated' }, 'load'); return }
        const token = this.requestId
        const identity = this.identity
        this.loading = true
        try {
          const raw = await api.summary(this.scenario)
          if (!this.current(token, identity)) return
          this.summary = normalizeSummary(raw, this.userId)
        } catch (error) {
          if (this.current(token, identity)) this.fail(error, 'load')
        } finally {
          if (this.current(token, identity)) this.loading = false
        }
      },
      async generate () {
        if (this.working || !this.canGenerate) return
        clearTimeout(this.timer)
        const token = ++this.requestId
        const identity = this.identity
        this.feedback = null
        this.openSource = null
        this.error = null
        this.polls = 0
        this.pollingPaused = false
        this.generating = true
        try {
          const raw = await api.generate(this.scenario)
          if (!this.current(token, identity)) return
          this.apply(raw)
        } catch (error) {
          if (this.current(token, identity)) this.fail(error, 'generate')
        } finally {
          if (this.current(token, identity)) this.generating = false
        }
      },
      apply (raw, generationId) {
        this.feedback = normalizeFeedback(raw, this.userId, generationId)
        if (this.feedback.status === 'generating') {
          this.pollingPaused = this.polls >= 10
          if (!this.pollingPaused) this.timer = setTimeout(this.checkResult, 3000)
        }
      },
      async checkResult () {
        if (this.working || !this.feedback || this.feedback.status !== 'generating') return
        clearTimeout(this.timer)
        const token = ++this.requestId
        const identity = this.identity
        const generationId = this.feedback.generation_id
        this.checking = true
        this.error = null
        this.polls++
        try {
          const raw = await api.result(generationId, this.scenario)
          if (!this.current(token, identity)) return
          this.apply(raw, generationId)
        } catch (error) {
          if (this.current(token, identity)) this.fail(error, 'check')
        } finally {
          if (this.current(token, identity)) this.checking = false
        }
      },
      handleError () {
        if (this.working || !this.error) return
        if (this.error.action === 'login') this.$store.dispatch('changeModalStatus', { mode: 'login', visible: true })
        else if (this.error.action === 'reload' || this.failedOperation === 'load') this.load()
        else if (this.failedOperation === 'generate') this.generate()
        else this.checkResult()
      }
    }
  }
</script>
<style lang="less" scoped>
  .learning-feedback { padding: 24px; color: #303b4b; line-height: 1.8; }
  .heading { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
  h2 { font-size: 21px; } h3 { font-size: 16px; }
  .muted { font-size: 12px; color: #687587; }
  .intro { margin: 4px 0 20px; }
  .record-summary { padding: 16px; background: #f6f8fb; border-radius: 6px; }
  .evidence { padding: 8px 0 0 20px; }
  .generate-intro { margin: 24px 0; }
  .section-title { margin: 24px 0 12px; }
  .overview { line-height: 1.9; }
  .point { padding: 14px 0; border-bottom: 1px solid #e7ecf2; }
  .point strong { margin-right: 12px; }
  .suggestions { padding-left: 22px; }
  .suggestions li { margin: 10px 0; }
  .source { padding: 12px 16px; border: 1px solid #e2e7ee; border-radius: 6px; margin-top: 10px; }
  blockquote { margin-top: 8px; padding: 10px 14px; border-left: 3px solid #b7d2ee; background: #f6f9fd; white-space: pre-line; }
  .footnote { margin-top: 14px; }
  .actions { display: flex; align-items: center; flex-wrap: wrap; gap: 20px; margin-top: 24px; }
  .empty { padding: 30px 0; text-align: center; line-height: 2.2; }
  .mock-controls { padding: 10px; background: #fff7e6; margin-bottom: 20px; font-size: 12px; }
  select { padding: 4px; max-width: 100%; }
  @media (max-width: 600px) { .learning-feedback { padding: 14px; } }
</style>
