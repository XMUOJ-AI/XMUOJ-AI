<template>
  <Card class="problem-guidance" dis-hover :padding="20">
    <div slot="title" class="guidance-heading">
      <span><Icon type="ios-lightbulb-outline"></Icon> 解题引导</span>
      <Tag v-if="isMock" color="blue">模拟演示</Tag>
      <Button type="text" size="small" :aria-expanded="String(expanded)" aria-controls="guidance-content" @click="expanded = !expanded">
        {{ expanded ? '收起' : '展开' }} <Icon :type="expanded ? 'chevron-up' : 'chevron-down'"></Icon>
      </Button>
    </div>
    <div v-show="expanded" id="guidance-content">
      <p class="intro">先独立思考，再说说你的理解。通过小步追问找到方向，每次只前进一步。</p>
      <Steps :current="session ? session.stage : 0" size="small" class="guidance-steps">
        <Step v-for="stage in stages" :key="stage.id" :title="stage.label"></Step>
      </Steps>
      <div aria-live="polite">
        <p v-if="!context" class="notice">{{ userId ? '题目上下文暂不可用。' : '登录后可查看本题是否开放解题引导。' }}</p>
        <p v-else-if="loading" class="notice"><Icon type="load-c" class="ivu-load-loop"></Icon> 正在检查引导状态…</p>
        <Alert v-else-if="error" type="warning" show-icon>{{ error }}</Alert>
        <Alert v-else-if="session" :type="session.status === 'failed' ? 'warning' : 'info'" show-icon>
          {{ statusText }}
        </Alert>
      </div>
      <template v-if="session">
        <div v-if="session.messages.length" class="messages" role="log" aria-label="本题引导记录">
          <div v-for="message in session.messages" :key="message.id" class="message" :class="message.role">
            <span class="speaker">{{ message.role === 'guide' ? '引导' : '我的思考' }} · {{ stageLabel(message.stage) }}</span>
            <p>{{ message.text }}</p>
          </div>
        </div>
        <p class="quota">本题剩余提示 {{ session.quota.remaining }} / {{ session.quota.limit }} 次 · 以服务端记录为准</p>
      </template>
      <form v-if="canCompose" @submit.prevent="send">
        <label for="guidance-thought" class="thought-label">{{ currentPrompt }}</label>
        <Input element-id="guidance-thought" v-model="thought" type="textarea" :rows="3" :maxlength="1000"
               :disabled="sending || !!retryPayload" placeholder="写下你对输入和目标的理解、已尝试的思路，以及还不确定的地方。"></Input>
        <div class="compose-footer">
          <span>{{ thought.trim().length }} / 1000 字<span v-if="validation" class="validation"> · {{ validation }}</span></span>
          <Button type="primary" html-type="submit" :loading="sending" :disabled="sending || !!retryPayload">提交思考，获取下一步引导</Button>
        </div>
      </form>
      <div class="actions">
        <Button v-if="retryPayload && context" type="primary" :loading="sending" :disabled="sending || loading" @click="retry">重试本次引导</Button>
        <Button v-if="context && !sending" type="ghost" :loading="loading" :disabled="loading" @click="load">
          {{ session && session.status === 'waiting' ? (seconds > 0 ? '刷新等待状态' : '检查是否可用') : '重新检查状态' }}
        </Button>
      </div>
      <p class="footnote">引导不提供完整题解或替代代码。倒计时、提示次数及比赛可用性由教学配置决定。</p>
    </div>
  </Card>
</template>

<script>
  import api from './problemGuidanceApi'
  import { id, stages, normalizeGuidance, errorMessage } from './problemGuidanceData'

  export default {
    name: 'ProblemGuidance',
    props: {
      problemId: { type: [String, Number], default: null },
      contestId: { type: [String, Number], default: null }
    },
    data () {
      return { expanded: true,
        stages,
        session: null,
        thought: '',
        error: '',
        validation: '',
        loading: false,
        sending: false,
        retryPayload: null,
        sequence: 0,
        timer: null,
        now: Date.now(),
        receivedAt: 0,
        alive: true }
    },
    computed: {
      isMock () { return process.env.AI_FEATURES_MOCK === true },
      userId () { return id((this.$store.getters.user || {}).id) },
      scenario () { return this.isMock && typeof this.$route.query.mock_guidance === 'string' ? this.$route.query.mock_guidance : '' },
      context () {
        const problem = id(this.problemId)
        const contest = id(this.contestId)
        if (!problem || !this.userId || (this.contestId != null && this.contestId !== '' && !contest)) return null
        return { problem_id: problem, contest_id: contest, user_id: this.userId }
      },
      identity () { return JSON.stringify([this.context, this.scenario]) },
      seconds () {
        if (!this.session || this.session.available_at === null) return 0
        return Math.max(0, Math.ceil((this.session.available_at - this.session.server_time - (this.now - this.receivedAt)) / 1000))
      },
      canCompose () {
        return !!(this.session && !this.error && this.session.allowed && this.session.quota.remaining > 0 &&
          ['ready', 'insufficient', 'failed'].includes(this.session.status))
      },
      currentPrompt () { return stages[this.session ? this.session.stage : 0].prompt },
      statusText () {
        const state = this.session
        if (!state) return ''
        if (state.status === 'unknown') return '引导状态待确认，请稍后重新检查。'
        if (!state.allowed || state.status === 'disabled') return state.message || '当前题目尚未开放解题引导。'
        const messages = {
          waiting: this.seconds > 0 ? `请先独立思考，约 ${this.seconds} 秒后可检查提示是否开放。` : '思考时间已到，请点击“检查是否可用”确认服务端状态。',
          ready: state.messages.length ? '结合已有追问补充你的思考，再进入下一步。' : '写下你已经理解的部分和卡点，我们从这里开始。',
          insufficient: '描述还不够具体，请补充题意、已经尝试的思路或卡点。本次不消耗提示。',
          generating: '本次引导正在准备中，请稍后重新检查状态。',
          failed: '本次引导未完成，可重试或重新检查状态。',
          exhausted: '本题提示次数已用完。试着整理已有引导，回到编辑器独立完成。'
        }
        return messages[state.status] || '引导状态待确认。'
      }
    },
    watch: {
      identity: { immediate: true, handler () { this.reset(); this.load() } }
    },
    beforeDestroy () { this.alive = false; this.sequence++; this.stopTimer() },
    methods: {
      stageLabel (stage) { return stages.find(item => item.id === stage).label },
      stopTimer () { clearInterval(this.timer); this.timer = null },
      reset () {
        this.sequence++
        this.stopTimer()
        this.session = null
        this.thought = this.error = this.validation = ''
        this.retryPayload = null
        this.loading = this.sending = false
      },
      current (token, identity) { return this.alive && this.sequence === token && this.identity === identity },
      definitiveError (error) {
        const status = error.response && error.response.status
        return (status >= 400 && status < 500 && status !== 408) ||
          (error.code && !['ECONNABORTED', 'ERR_NETWORK'].includes(error.code))
      },
      accept (raw, context) {
        this.session = normalizeGuidance(raw, context)
        this.receivedAt = this.now = Date.now()
        this.stopTimer()
        if (this.session.status === 'waiting') {
          this.timer = setInterval(() => {
            this.now = Date.now()
            if (this.seconds === 0) this.stopTimer()
          }, 1000)
        }
      },
      async load () {
        if (!this.context || this.sending) return
        const context = this.context
        const identity = this.identity
        const token = ++this.sequence
        this.loading = true
        this.error = ''
        // Fail closed while checking, retaining input and any uncertain POST key.
        this.session = null
        this.stopTimer()
        try {
          const raw = await api.get(context, this.scenario)
          if (!this.current(token, identity)) return
          this.accept(raw, context)
          // A status read can resolve an uncertain POST; never resend an accepted message.
          if (this.retryPayload) {
            if (raw.last_request_id === this.retryPayload.request_id) {
              this.thought = this.validation = ''
              this.retryPayload = null
            } else if (this.session.session_id !== this.retryPayload.session_id || !this.session.allowed) {
              this.retryPayload = null
            }
          }
        } catch (error) {
          if (this.current(token, identity)) {
            this.error = errorMessage(error)
            if (this.definitiveError(error)) this.retryPayload = null
          }
        } finally {
          if (this.current(token, identity)) this.loading = false
        }
      },
      send () {
        if (!this.canCompose || this.sending || this.retryPayload) return
        const text = this.thought.trim()
        if (text.length < 12 || text.length > 1000) { this.validation = '请用 12–1000 字具体描述'; return }
        this.validation = ''
        this.request({ session_id: this.session.session_id,
          text,
          request_id: 'guidance-' + Date.now().toString(36) + '-' + Math.random().toString(36).slice(2, 12) })
      },
      retry () {
        if (!this.retryPayload || this.sending || this.loading) return
        this.request(this.retryPayload)
      },
      async request (payload) {
        if (!this.context) return
        const context = this.context
        const identity = this.identity
        const token = ++this.sequence
        this.sending = true
        this.error = ''
        this.retryPayload = payload
        try {
          const raw = await api.send(context, this.scenario, payload)
          if (!this.current(token, identity)) return
          this.accept(raw, Object.assign({}, context, { session_id: payload.session_id }))
          if (!['failed', 'generating'].includes(this.session.status) || !this.session.allowed) this.retryPayload = null
          if (raw.last_request_id === payload.request_id) this.thought = ''
        } catch (error) {
          if (!this.current(token, identity)) return
          this.error = errorMessage(error)
          if (this.definitiveError(error)) {
            this.session = null
            this.retryPayload = null
          }
        } finally {
          if (this.current(token, identity)) this.sending = false
        }
      }
    }
  }
</script>

<style lang="less" scoped>
  .problem-guidance { margin-top: 20px; }
  .guidance-heading { display: flex; align-items: center; gap: 8px; }
  .guidance-heading button { margin-left: auto; }
  .intro { margin-bottom: 18px; color: #495060; }
  .guidance-steps { margin-bottom: 20px; }
  .notice, .quota, .footnote { color: #657180; line-height: 1.7; margin: 10px 0; }
  .quota, .footnote { font-size: 12px; }
  .messages { max-height: 380px; overflow: auto; margin: 16px 0; }
  .message { padding: 12px 16px; margin-bottom: 10px; border-radius: 4px; background: #f5f7f9; }
  .message.guide { background: #f0f7ff; border-left: 3px solid #2d8cf0; }
  .message p { white-space: pre-wrap; overflow-wrap: break-word; line-height: 1.8; margin-top: 6px; }
  .speaker { color: #657180; font-size: 12px; }
  .thought-label { display: block; margin: 14px 0 8px; }
  .compose-footer { display: flex; align-items: center; justify-content: space-between; gap: 10px; margin-top: 10px; color: #80848f; font-size: 12px; flex-wrap: wrap; }
  .validation { color: #bb7200; }
  .actions { margin-top: 12px; display: flex; gap: 8px; }
  .footnote { margin-bottom: 0; }
  @media (max-width: 650px) { .guidance-steps { overflow-x: auto; } }
</style>
