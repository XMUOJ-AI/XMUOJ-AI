<template>
  <section class="agent-run" aria-live="polite">
    <p v-if="error" role="alert">{{ error }}</p>
    <p v-if="busy">{{ status === 'queued' ? '任务已排队，正在等待生成…' : '正在生成并检查结果…' }}</p>
    <template v-if="result">
      <template v-if="request.service_type === 'code_explanation'">
        <p>{{ result.summary }}</p>
        <section v-for="(item, index) in result.sections" :key="index"><h4>{{ item.title }}</h4><p>{{ item.explanation }}</p><small v-if="item.code_refs.length">代码位置：{{ item.code_refs.join('、') }}</small></section>
        <h4>复杂度</h4><p>时间：{{ result.complexity.time }}；空间：{{ result.complexity.space }}</p>
        <ul><li v-for="item in result.complexity.assumptions" :key="item">{{ item }}</li></ul>
        <h4 v-if="result.improvement_directions.length">改进方向</h4><ul><li v-for="item in result.improvement_directions" :key="item">{{ item }}</li></ul>
      </template>
      <template v-else-if="request.service_type === 'learning_path_explanation'">
        <p>{{ result.overview }}</p><ol><li v-for="item in result.steps" :key="item.order">{{ item.knowledge_code }}：{{ item.reason }}</li></ol><p>{{ result.next_action }}</p>
      </template>
      <template v-else><p>{{ result.focus }}</p><p>{{ result.question }}</p></template>
    </template>
    <Button v-if="!result" type="primary" :loading="busy" :disabled="disabled || busy" @click="generate">{{ attempt.runId ? '继续查看' : error ? '重试本次请求' : label }}</Button>
    <Button v-if="error && !busy && attempt.key" type="text" @click="reset">放弃本次等待</Button>
    <p class="notice">仅在点击后生成；由服务端检查权限与资料，结果供学习参考。</p>
  </section>
</template>
<script>
  import { runAgent, errorText } from '@/api/agent'
  export default {
    props: { request: { type: Object, required: true }, disabled: Boolean, label: { type: String, default: '生成解释' } },
    emits: ['busy', 'pending', 'succeeded'],
    data () { return { attempt: {}, busy: false, error: '', result: null, status: '', sequence: 0, alive: true } },
    computed: { identity () { return JSON.stringify([this.$store.getters.user.id, this.request]) } },
    watch: { identity () { this.reset() } },
    beforeUnmount () { this.alive = false; this.sequence++ },
    methods: {
      reset () { this.sequence++; this.attempt = {}; this.busy = false; this.error = ''; this.result = null; this.$emit('busy', false); this.$emit('pending', false) },
      async generate () {
        if (this.busy || this.disabled || this.result) return
        const sequence = ++this.sequence
        const identity = this.identity
        const current = () => this.alive && this.sequence === sequence && this.identity === identity
        this.busy = true; this.error = ''; this.$emit('busy', true); this.$emit('pending', true)
        try {
          const run = await runAgent(this.request, this.attempt, { current, progress: value => { if (current()) this.status = value } })
          if (!current()) return
          this.result = run.result
          this.$emit('pending', false)
          this.$emit('succeeded', run.result)
        } catch (error) {
          if (!current()) return
          this.error = errorText(error)
          if (error.terminal || (error.status >= 400 && error.status < 500 && error.status !== 408)) { this.attempt = {}; this.$emit('pending', false) }
        } finally { if (current()) { this.busy = false; this.$emit('busy', false) } }
      }
    }
  }
</script>
<style scoped>
.agent-run { margin-top: 14px; }.agent-run p, .agent-run li { white-space: pre-wrap; overflow-wrap: anywhere; line-height: 1.8; }.agent-run h4 { margin-top: 14px; }.agent-run ul, .agent-run ol { padding-left: 22px; }.notice, small { color: #657180; }.notice { margin-top: 10px; font-size: 12px; }[role="alert"] { color: #a65228; margin-bottom: 10px; }
</style>
