<template><div class="echarts" /></template>
<script>
  import { markRaw } from 'vue'
  import echarts from 'echarts/lib/echarts'
  import 'echarts/lib/chart/bar'
  import 'echarts/lib/chart/line'
  import 'echarts/lib/chart/pie'
  import 'echarts/lib/component/title'
  import 'echarts/lib/component/grid'
  import 'echarts/lib/component/dataZoom'
  import 'echarts/lib/component/legend'
  import 'echarts/lib/component/tooltip'
  import 'echarts/lib/component/toolbox'
  import 'echarts/lib/component/markPoint'

  export default {
    name: 'ECharts',
    props: {
      options: { type: Object, default: () => ({}) },
      initOptions: { type: Object, default: () => ({}) },
      autoResize: Boolean
    },
    data () { return { chart: null, observer: null } },
    mounted () {
      this.chart = markRaw(echarts.init(this.$el, null, this.initOptions))
      this.chart.setOption(this.options, true)
      if (this.autoResize) {
        window.addEventListener('resize', this.resize)
        if (typeof ResizeObserver !== 'undefined') {
          this.observer = markRaw(new ResizeObserver(() => this.resize()))
          this.observer.observe(this.$el)
        }
      }
    },
    beforeUnmount () {
      window.removeEventListener('resize', this.resize)
      if (this.observer) this.observer.disconnect()
      if (this.chart) this.chart.dispose()
      this.chart = null
    },
    methods: {
      resize () { if (this.chart) this.chart.resize() },
      showLoading (options) { if (this.chart) this.chart.showLoading('default', options) },
      hideLoading () { if (this.chart) this.chart.hideLoading() }
    },
    watch: { options: { deep: true, handler (options) { if (this.chart) this.chart.setOption(options, true) } } }
  }
</script>
<style scoped>.echarts { width: 600px; height: 400px; }</style>
