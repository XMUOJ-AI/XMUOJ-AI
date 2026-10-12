<template>
  <section class="live-guidance" aria-label="解题引导">
    <h3>解题引导</h3><p>先独立思考，再说说你的理解，通过追问逐步找到方向。</p>
    <p v-if="!userId">登录后可使用解题引导。</p><p v-else-if="contestId">当前服务暂不支持比赛或实验题目的解题引导。</p>
    <template v-else>
      <p v-if="loading">正在读取引导状态…</p><Alert v-if="error" type="warning" show-icon>{{ error }}</Alert>
      <template v-if="conversation">
        <p>已使用 {{ conversation.hint_level }} / {{ conversation.max_hint_level }} 级提示。</p>
        <p v-if="seconds > 0">请先独立思考，预计 {{ seconds }} 秒后可申请提示；实际可用时间由服务端确认。</p>
        <p v-if="conversation.hint_level >= conversation.max_hint_level">已达到本题提示上限，请结合已有引导继续独立练习。</p>
        <div v-for="(item, index) in history" :key="index" class="message"><p>我的思考：{{ item.thought }}</p><strong>第 {{ item.result.hint_level }} 级引导 · {{ item.result.focus }}</strong><p>{{ item.result.question }}</p></div>
        <form @submit.prevent>
          <label for="live-guidance-thought">描述你的理解、已尝试的思路和卡点</label>
          <textarea id="live-guidance-thought" v-model="thought" rows="3" maxlength="4000" :disabled="pending || busy || loading || exhausted" />
          <AgentRun :request="request" :disabled="!canRequest" label="提交思考，获取下一步引导" @busy="busy = $event" @pending="pending = $event" @succeeded="acceptHint" />
        </form>
      </template>
      <Button :loading="loading" :disabled="loading || busy || pending || !userId" @click="load">重新检查状态</Button>
      <p class="notice">当前页面展示本次访问中生成的引导；提示级别与等待时间保存在服务端。</p>
    </template>
  </section>
</template>
<script>
  import AgentRun from '@oj/components/AgentRun.vue'
  import { startConversation, errorText } from '@/api/agent'
  export default {
    components: { AgentRun },
    props: { problemId: { type: [String, Number], default: null }, contestId: { type: [String, Number], default: null } },
    data () { return { conversation: null, loading: false, busy: false, pending: false, thought: '', history: [], error: '', sequence: 0, alive: true, now: Date.now(), timer: null } },
    computed: {
      userId () { return this.$store.getters.user.id },
      identity () { return JSON.stringify([this.userId, this.problemId, this.contestId]) },
      seconds () { return this.conversation ? Math.max(0, Math.ceil((Date.parse(this.conversation.hint_available_time) - this.now) / 1000)) : 0 },
      exhausted () { return this.conversation && this.conversation.hint_level >= this.conversation.max_hint_level },
      canRequest () { return Boolean(this.conversation && this.conversation.status === 'active' && !this.loading && !this.error && !this.exhausted && this.seconds === 0 && this.thought.trim()) },
      request () { return { service_type: 'socratic_hint', problem_id: String(this.problemId), conversation_id: this.conversation ? this.conversation.conversation_id : '', student_explanation: this.thought.trim() } }
    },
    watch: { identity: { immediate: true, handler () {
      this.sequence++; clearInterval(this.timer); this.conversation = null; this.history = []; this.thought = this.error = ''; this.busy = this.pending = this.loading = false; this.load()
    } } },
    beforeUnmount () { this.alive = false; this.sequence++; clearInterval(this.timer) },
    methods: {
      async load () {
        if (!this.userId || !this.problemId || this.contestId || this.loading) return
        const sequence = ++this.sequence; const identity = this.identity
        const current = () => this.alive && this.sequence === sequence && this.identity === identity
        this.loading = true; this.error = ''
        try {
          const value = await startConversation(this.problemId)
          if (!current()) return
          if (!value || String(value.problem_id) !== String(this.problemId) || value.service_type !== 'socratic_hint' || typeof value.conversation_id !== 'string' ||
            !Number.isInteger(value.hint_level) || value.hint_level < 0 || value.hint_level > 3 || value.max_hint_level !== 3 || !Number.isFinite(Date.parse(value.hint_available_time))) throw new Error('引导状态数据不完整。')
          this.conversation = value; this.now = Date.now(); clearInterval(this.timer)
          if (this.seconds > 0) this.timer = setInterval(() => { this.now = Date.now(); if (this.seconds === 0) clearInterval(this.timer) }, 1000)
        } catch (error) { if (current()) { this.conversation = null; this.error = errorText(error) } }
        finally { if (current()) this.loading = false }
      },
      acceptHint (result) { this.history.push({ thought: this.thought, result }); this.thought = ''; this.pending = false; this.load() }
    }
  }
</script>
<style scoped>.live-guidance { margin: 20px 0; padding: 20px; background: white; border: 1px solid #e8eaec; border-radius: 5px; }.live-guidance p { white-space: pre-wrap; overflow-wrap: anywhere; line-height: 1.8; margin: 12px 0; }label { display: block; margin-top: 14px; }textarea { display: block; width: 100%; padding: 10px; margin-top: 8px; border: 1px solid #dcdee2; border-radius: 4px; font: inherit; }.message { background: #f3f8ff; padding: 12px; margin-top: 12px; }.notice { color: #657180; font-size: 12px; }</style>
