<template><div><textarea ref="input" /></div></template>
<script>
  import { markRaw } from 'vue'
  import CodeMirror from 'codemirror'
  import 'codemirror/lib/codemirror.css'

  export default {
    name: 'CodeMirrorInput',
    props: { value: { type: String, default: '' }, options: { type: Object, default: () => ({}) } },
    emits: ['change'],
    data () { return { editor: null, syncingValue: false } },
    mounted () {
      this.editor = markRaw(CodeMirror.fromTextArea(this.$refs.input, this.options))
      this.editor.setValue(this.value)
      this.editor.on('change', this.onChange)
    },
    beforeUnmount () {
      if (this.editor) {
        this.editor.off('change', this.onChange)
        this.editor.toTextArea()
        this.editor = null
      }
    },
    methods: {
      onChange () {
        if (this.editor && !this.syncingValue) this.$emit('change', this.editor.getValue())
      }
    },
    watch: {
      value (value) {
        if (!this.editor || value === this.editor.getValue()) return
        const cursor = this.editor.getCursor()
        const scroll = this.editor.getScrollInfo()
        this.syncingValue = true
        try {
          this.editor.setValue(value)
          this.editor.setCursor(cursor)
          this.editor.scrollTo(scroll.left, scroll.top)
        } finally {
          this.syncingValue = false
        }
      },
      options: {
        deep: true,
        handler (options) {
          if (this.editor) Object.keys(options).forEach(key => this.editor.setOption(key, options[key]))
        }
      }
    }
  }
</script>
