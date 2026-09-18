<template>
  <Collapse v-model="expanded" class="submission-analysis">
    <CollapsePanel name="analysis">
      提交代码解读 <Tag v-if="mockEnabled" color="blue">模拟演示</Tag>
      <div slot="content" aria-live="polite">
        <p class="notice">解读仅提供可能的思路与排查方向，以原判题结果为准；一次 AC 不能证明已掌握相关知识点。不提供完整替代代码。</p>
        <p v-if="mockEnabled" class="notice">以下为固定示例，未调用真实 AI。权限、竞赛与实验限制为拟定服务端契约。</p>
        <Alert v-if="state !== 'ready'" :type="alertType" show-icon>{{message}}</Alert>
        <template v-if="state === 'ready' && result">
          <Alert :type="result.scope.truncated ? 'warning' : 'info'" show-icon>
            分析范围：第 {{result.scope.start_line}}–{{result.scope.end_line}} 行，共 {{result.scope.total_lines}} 行。
            <span v-if="result.scope.truncated">代码已截断，仅讨论所列范围，无法对完整程序下结论。</span>
            <span v-else>范围覆盖本次提交的全部代码；结论仍可能有误。</span>
          </Alert>
          <p class="summary">{{result.summary}}</p>
          <section v-for="(section, index) in result.sections" :key="index" class="analysis-section">
            <h4>{{section.title}}</h4>
            <p>{{section.body}}</p>
            <p class="evidence">依据：{{section.evidence}}</p>
          </section>
          <p class="notice">当前结果已保留，折叠后再展开不会重复生成。分析版本：{{version}}</p>
        </template>
        <Button v-if="state === 'idle'" type="primary" @click="generate">生成本次提交解读</Button>
        <Button v-if="state === 'generating' || state === 'checking'" :loading="true" disabled>{{state === 'checking' ? '检查权限中' : '生成中'}}</Button>
        <Button v-if="canRetry" @click="checkCapability">重新检查</Button>
      </div>
    </CollapsePanel>
  </Collapse>
</template>

<script>
import {Collapse, Panel as CollapsePanel} from 'iview'
import api from './submissionAnalysisApi'
import {ANALYSIS_VERSION, localState, messages, normalizeCapability, normalizeAnalysis, errorState, createRequestGuard} from './submissionAnalysisData'

export default {
  name: 'SubmissionAnalysis',
  components: {Collapse, CollapsePanel},
  props: {submission: {type: Object, required: true}},
  data () {
    return {expanded: [], state: 'checking', result: null, revision: null, version: ANALYSIS_VERSION}
  },
  computed: {
    mockEnabled () { return process.env.AI_FEATURES_MOCK === true },
    userId () { return this.$store.getters.user.id },
    scenario () { return this.mockEnabled ? this.$route.query.mock_analysis : undefined },
    contextKey () {
      const s = this.submission
      return JSON.stringify([this.$route.params.id, this.userId, s.id, s.user_id, s.result, s.code, s.statistic_info, s.info, this.scenario])
    },
    message () { return messages[this.state] || messages.unavailable },
    alertType () { return ['failed', 'invalid_response'].indexOf(this.state) !== -1 ? 'warning' : 'info' },
    canRetry () { return ['failed', 'invalid_response', 'busy', 'quota_exceeded', 'login_required', 'forbidden', 'unavailable', 'insufficient_evidence'].indexOf(this.state) !== -1 }
  },
  watch: {
    contextKey () { this.reset() }
  },
  created () {
    this.requestGuard = createRequestGuard()
    this.reset()
  },
  beforeDestroy () { this.requestGuard.invalidate() },
  methods: {
    reset () {
      this.requestGuard.invalidate()
      this.expanded = []
      this.result = null
      this.revision = null
      this.checkCapability()
    },
    identity () {
      return {submission_id: this.submission.id, user_id: this.userId, judge_result: this.submission.result, judge_revision: this.revision, analysis_version: this.version}
    },
    checkCapability () {
      const key = this.contextKey
      const ticket = this.requestGuard.next()
      this.result = null
      this.revision = null
      this.state = localState(this.submission, this.userId)
      if (this.state !== 'idle') return
      this.state = 'checking'
      const expected = this.identity()
      api.capability(this.submission.id, this.scenario).then(data => {
        if (!this.requestGuard.current(ticket, key, this.contextKey)) return
        const normalized = normalizeCapability(data, expected)
        this.state = normalized.state
        this.revision = normalized.revision || null
      }).catch(error => {
        if (this.requestGuard.current(ticket, key, this.contextKey)) this.state = errorState(error)
      })
    },
    generate () {
      if (this.state !== 'idle' || !this.revision || localState(this.submission, this.userId) !== 'idle') return
      const key = this.contextKey
      const ticket = this.requestGuard.next()
      const expected = this.identity()
      this.state = 'generating'
      api.generate(expected, this.scenario).then(data => {
        if (!this.requestGuard.current(ticket, key, this.contextKey)) return
        const normalized = normalizeAnalysis(data, expected)
        this.result = normalized.result || null
        this.state = normalized.state
      }).catch(error => {
        if (this.requestGuard.current(ticket, key, this.contextKey)) this.state = errorState(error)
      })
    }
  }
}
</script>

<style scoped lang="less">
.submission-analysis {
  margin: 18px 0;
  .notice { color: #657180; line-height: 1.7; margin-bottom: 12px; }
  .summary { margin: 14px 0; line-height: 1.8; }
  .analysis-section { padding: 12px 0; border-top: 1px solid #e9eaec; }
  h4 { margin-bottom: 6px; }
  p { white-space: pre-wrap; overflow-wrap: break-word; line-height: 1.8; }
  .evidence { color: #657180; font-size: 12px; margin-top: 6px; }
}
</style>
