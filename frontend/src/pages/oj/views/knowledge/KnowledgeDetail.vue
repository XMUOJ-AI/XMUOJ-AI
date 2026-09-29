<template>
  <main class="detail-page"><NotFound v-if="notFound" /><template v-else><router-link :to="{ name: 'knowledge' }">← 知识点探索</router-link><div v-if="loading" class="state" role="status">正在加载知识点…</div><div v-else-if="error" class="state error" role="alert">{{ error }} <Button size="small" @click="load">重试</Button></div><template v-else-if="point"><header class="hero"><span class="eyebrow">KNOWLEDGE POINT</span><h1>{{ point.name }}</h1><code>{{ point.code }}</code><div class="badges"><Tag color="blue">{{ categoryLabel(point.category) }}</Tag><Tag color="green">L{{ point.level }}</Tag></div><p>{{ point.description || '暂无描述' }}</p><div v-if="point.aliases.length" class="aliases">别名：{{ point.aliases.join('、') }}</div><router-link :to="{ name: 'knowledge-graph', query: { root_code: point.code } }">在完整图谱中查看 →</router-link></header><div class="sections"><section class="card"><h2>前置知识点</h2><p v-if="!point.prerequisites.length" class="empty">暂无前置知识点</p><ul v-else><li v-for="item in point.prerequisites" :key="item.code"><router-link :to="{ name: 'knowledge-detail', params: { code: item.code } }">{{ item.name }}</router-link><small>{{ item.code }} · {{ relationLabel(item.relation_type) }}</small></li></ul></section><section class="card"><h2>后继知识点</h2><p v-if="!point.dependents.length" class="empty">暂无后继知识点</p><ul v-else><li v-for="item in point.dependents" :key="item.code"><router-link :to="{ name: 'knowledge-detail', params: { code: item.code } }">{{ item.name }}</router-link><small>{{ item.code }} · {{ relationLabel(item.relation_type) }}</small></li></ul></section><section class="card problems"><h2>关联题目</h2><p v-if="!point.related_problems.length" class="empty">暂无可见的关联题目</p><ul v-else><li v-for="problem in point.related_problems" :key="problem.display_id"><router-link :to="{ name: 'problem-details', params: { problemID: problem.display_id } }">{{ problem.display_id }} · {{ problem.title }}</router-link></li></ul></section></div></template></template></main>
</template>
<script>
  import { mapGetters } from 'vuex'
  import { getKnowledge } from './knowledgeApi'
  import { categoryLabel, errorMessage } from './knowledgeData'
  import NotFound from '../general/404.vue'
  export default {
    components: { NotFound },
    data () { return { point: null, loading: false, error: '', notFound: false, request: 0, alive: true } },
    computed: { ...mapGetters(['isAuthenticated']) },
    mounted () { this.load() },
    beforeUnmount () { this.alive = false; this.request++ },
    watch: { '$route.params.code' () { this.load() }, isAuthenticated (value) { if (!value) { this.request++; this.point = null; this.loading = false } } },
    methods: {
      categoryLabel,
      relationLabel (type) { return type === 'required' ? '必需依赖' : '推荐依赖' },
      async load () {
        const request = ++this.request
        this.point = null; this.error = ''; this.notFound = false; this.loading = true
        try { const data = await getKnowledge(this.$route.params.code); if (this.alive && request === this.request) this.point = data } catch (error) { if (this.alive && request === this.request) { this.error = errorMessage(error); this.notFound = error.status === 404 } } finally { if (this.alive && request === this.request) this.loading = false }
      }
    }
  }
</script>
<style scoped>
  .detail-page { max-width: 1100px; margin: 0 auto; color: #26364a; }.hero, .card { background: white; border: 1px solid #e4eaf2; border-radius: 10px; box-shadow: 0 5px 22px rgba(30,57,91,.05); padding: 26px; }.hero { margin-top: 20px; }.eyebrow { color: #2d8cf0; font-size: 11px; font-weight: 700; letter-spacing: .12em; }.hero h1 { font-size: 29px; margin: 8px 0 2px; }.hero code { color: #8391a5; }.badges { margin: 20px 0; }.hero p { line-height: 1.8; white-space: pre-wrap; }.aliases { color: #748398; margin: 18px 0; }.sections { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin-top: 20px; }.card h2 { font-size: 18px; margin: 0 0 16px; }.card ul { list-style: none; padding: 0; }.card li { padding: 11px 0; border-top: 1px solid #edf1f6; }.card small { display: block; color: #8b98a8; margin-top: 3px; }.problems { grid-column: 1 / -1; }.empty { color: #8b98a8; }.state { padding: 100px 20px; text-align: center; color: #8391a5; }.error { color: #b94b4b; }@media(max-width:700px) { .sections { grid-template-columns: 1fr; }.problems { grid-column: 1; } }
</style>
