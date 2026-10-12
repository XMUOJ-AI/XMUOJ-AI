<template>
  <section class="live-path" aria-label="学习路径" aria-live="polite">
    <div class="heading"><h2>学习路径</h2><Button :loading="loading" :disabled="loading || !userId" @click="load">更新进度</Button><Button :loading="creating" :disabled="loading || creating || !userId" @click="generate">{{ path ? '生成新路径' : '生成学习路径' }}</Button></div>
    <p v-if="!userId">登录后可查看自己的学习路径。</p><p v-else-if="loading">正在获取活动学习路径…</p>
    <Alert v-if="error" type="warning" show-icon>{{ error }}</Alert>
    <Alert v-if="outdated" type="info" show-icon>返回链接对应的路径已变化，当前服务只提供活动路径。<Button type="text" @click="viewLatest">查看当前路径</Button></Alert>
    <p v-if="empty">尚未生成活动学习路径，可以点击“生成学习路径”。</p>
    <template v-if="path && !outdated">
      <p v-if="path.target">学习目标：{{ path.target.name }}</p>
      <p class="notice">推荐由练习记录和知识依赖生成；点击“更新进度”可重新读取服务端判题进度。</p>
      <p v-if="!path.steps.length">当前没有可推荐的学习步骤。</p>
      <article v-for="step in path.steps" :key="step.order" :class="{ selected: String(step.order) === String($route.query.step) }">
        <h3>{{ step.order }}. {{ step.knowledge_name }} <small>{{ statusLabel(step.status) }}</small></h3>
        <p>{{ step.reason_text }}</p>
        <router-link v-if="step.problem_id" :to="problemLink(step)">{{ step.problem_id }} · {{ step.title }} → {{ step.status === 'completed' ? '再次练习' : '开始练习' }}</router-link>
        <p v-else class="notice">当前步骤暂无可访问的练习题。</p>
      </article>
      <AgentRun v-if="path.steps.length" :key="path.path_id" :request="{ service_type: 'learning_path_explanation', path_id: path.path_id }" label="解释这条路径的推荐依据" />
    </template>
  </section>
</template>
<script>
  import AgentRun from '@oj/components/AgentRun.vue'
  import { getCurrentPath, refreshPath } from './learningPathApi'
  import { requestKey, errorText } from '@/api/agent'
  import { statusLabel as prototypeStatusLabel } from './learningPathData'
  export default {
    components: { AgentRun },
    data () { return { path: null, empty: false, outdated: false, error: '', loading: false, creating: false, sequence: 0, alive: true, refreshKey: null } },
    computed: {
      userId () { return this.$store.getters.user.id },
      identity () { return JSON.stringify([this.userId, this.$route.query.path, this.$route.query.revision]) }
    },
    watch: { identity: { immediate: true, handler (value, previous) {
      this.sequence++; this.path = null; this.empty = this.outdated = false; this.error = ''; this.loading = this.creating = false; this.refreshKey = null
      if (previous && JSON.parse(previous)[0] && JSON.parse(previous)[0] !== this.userId) {
        const query = { ...this.$route.query }; delete query.path; delete query.revision; delete query.step
        this.$router.replace({ query }).catch(() => {})
      }
      this.load()
    } } },
    beforeUnmount () { this.alive = false; this.sequence++ },
    methods: {
      statusLabel (value) { return value === 'in_progress' ? '进行中' : prototypeStatusLabel(value) },
      current (sequence, identity) { return this.alive && sequence === this.sequence && identity === this.identity },
      async load () {
        if (!this.userId || this.creating) return
        const sequence = ++this.sequence; const identity = this.identity
        this.loading = true; this.error = ''; this.empty = false
        try {
          const path = await getCurrentPath()
          if (!this.current(sequence, identity)) return
          this.path = path
          this.outdated = Boolean((this.$route.query.path && this.$route.query.path !== path.path_id) || this.$route.query.revision)
        } catch (error) {
          if (!this.current(sequence, identity)) return
          if (error.code === 'LEARNING_PATH_NOT_FOUND') { this.path = null; this.empty = true }
          else { this.path = null; this.error = errorText(error) }
        } finally { if (this.current(sequence, identity)) this.loading = false }
      },
      async generate () {
        if (!this.userId || this.creating || this.loading) return
        const sequence = ++this.sequence; const identity = this.identity
        this.creating = true; this.error = ''
        if (!this.refreshKey) this.refreshKey = requestKey()
        try {
          const path = await refreshPath(this.refreshKey)
          if (!this.current(sequence, identity)) return
          this.path = path; this.refreshKey = null; this.empty = this.outdated = false
          const query = { ...this.$route.query, path: path.path_id }; delete query.revision; delete query.step
          await this.$router.replace({ query })
        } catch (error) { if (this.current(sequence, identity)) { this.error = errorText(error); if (error.status >= 400 && error.status < 500) this.refreshKey = null } }
        finally { if (this.current(sequence, identity)) this.creating = false }
      },
      viewLatest () { const query = { ...this.$route.query }; delete query.path; delete query.revision; delete query.step; this.$router.replace({ query }).catch(() => {}) },
      problemLink (step) { return { name: 'problem-details', params: { problemID: step.problem_id }, query: { from: 'learning-path', path: this.path.path_id, step: String(step.order) } } }
    }
  }
</script>
<style scoped>.heading { display: flex; align-items: center; gap: 12px; margin-bottom: 16px; }.heading h2 { margin-right: auto; }.live-path p { line-height: 1.8; margin: 12px 0; }article { padding: 16px; margin-top: 12px; border: 1px solid #e8eaec; border-radius: 5px; }article.selected { border-color: #2d8cf0; }.notice, small { color: #657180; }small { font-size: 12px; font-weight: normal; }</style>
