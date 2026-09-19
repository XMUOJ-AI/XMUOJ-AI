<template>
  <div class="vue-codemirror-wrap"><textarea ref="editor"></textarea></div>
</template>

<script>
  import { markRaw } from 'vue'
  import CodeMirror from 'codemirror'
  import 'codemirror/lib/codemirror.css'
  import 'codemirror/mode/clike/clike.js'
  import 'codemirror/mode/python/python.js'
  import 'codemirror/theme/solarized.css'

  export default {
    name: 'CodeMirror',
    emits: ['update:modelValue', 'change'],
    props: {
      modelValue: { type: String, default: '' },
      mode: { type: String, default: 'text/x-csrc' }
    },
    data () {
      return { editor: null }
    },
    mounted () {
      this.editor = markRaw(CodeMirror.fromTextArea(this.$refs.editor, {
        mode: this.mode,
        lineNumbers: true,
        lineWrapping: false,
        theme: 'solarized',
        tabSize: 4,
        line: true,
        foldGutter: true,
        gutters: ['CodeMirror-linenumbers', 'CodeMirror-foldgutter'],
        autofocus: true
      }))
      this.editor.setValue(this.modelValue)
      this.editor.on('change', this.onEditorChange)
      this.$nextTick(() => this.editor && this.editor.refresh())
    },
    beforeUnmount () {
      if (this.editor) {
        this.editor.off('change', this.onEditorChange)
        this.editor.toTextArea()
        this.editor = null
      }
    },
    methods: {
      onEditorChange (editor) {
        const value = editor.getValue()
        if (value !== this.modelValue) {
          this.$emit('update:modelValue', value)
          this.$emit('change', value)
        }
      }
    },
    watch: {
      modelValue (value) {
        if (this.editor && this.editor.getValue() !== value) {
          const cursor = this.editor.getCursor()
          const scroll = this.editor.getScrollInfo()
          this.editor.setValue(value)
          this.editor.setCursor(cursor)
          this.editor.scrollTo(scroll.left, scroll.top)
        }
      },
      mode (mode) {
        if (this.editor) this.editor.setOption('mode', mode)
      }
    }
  }
</script>

<style>
  .CodeMirror-code {
    font-family: Menlo, Monaco, Consolas, "Courier New", monospace;
  }

  .CodeMirror {
    height: auto !important;
  }

  .CodeMirror-scroll {
    min-height: 300px;
    max-height: 1000px;
  }
</style>
