<template>
  <details class="live-analysis"><summary>提交代码解读</summary>
    <p v-if="state !== 'idle'">{{ message }}</p>
    <AgentRun v-else :key="contextKey" :request="request" label="生成本次提交解读" />
  </details>
</template>
<script>
  import AgentRun from '@oj/components/AgentRun.vue'
  import { sameId, messages } from './submissionAnalysisData'
  export default {
    components: { AgentRun },
    props: { submission: { type: Object, required: true } },
    computed: {
      state () {
        const userId = this.$store.getters.user.id
        if (!userId) return 'login_required'
        if (!this.submission.id) return 'unavailable'
        if (!sameId(this.submission.user_id, userId)) return 'forbidden'
        if (this.submission.result === -2) return 'compile_error'
        if ([6, 7, 9].includes(this.submission.result)) return 'pending'
        return [0, -1, 1, 2, 3, 4, 8].includes(this.submission.result) ? 'idle' : 'unavailable'
      },
      message () { return messages[this.state] },
      request () { return { service_type: 'code_explanation', submission_id: String(this.submission.id) } },
      contextKey () { return JSON.stringify([this.$store.getters.user.id, this.submission]) }
    }
  }
</script>
<style scoped>.live-analysis { margin: 18px 0; border: 1px solid #e8eaec; border-radius: 4px; padding: 16px; }summary { cursor: pointer; font-weight: 600; }p { margin-top: 12px; }</style>
