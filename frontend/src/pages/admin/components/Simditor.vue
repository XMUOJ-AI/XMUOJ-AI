<template>
  <textarea ref="editor"></textarea>
</template>

<script>
  import { markRaw } from 'vue'
  import Simditor from 'tar-simditor'
  import 'tar-simditor/styles/simditor.css'
  import 'tar-simditor-markdown'
  import 'tar-simditor-markdown/styles/simditor-markdown.css'
  import './simditor-file-upload'

  export default {
    name: 'Simditor',
    emits: ['update:modelValue', 'change'],
    props: {
      toolbar: {
        type: Array,
        default: () => ['title', 'bold', 'italic', 'underline', 'fontScale', 'color', 'ol', 'ul', '|', 'blockquote', 'code', 'link', 'table', 'image', 'uploadfile', 'hr', '|', 'indent', 'outdent', 'alignment', '|', 'markdown']
      },
      modelValue: { type: String, default: '' }
    },
    data () {
      return { editor: null, updatingValue: false }
    },
    mounted () {
      this.editor = markRaw(new Simditor({
        textarea: this.$refs.editor,
        toolbar: this.toolbar,
        pasteImage: true,
        markdown: false,
        upload: {
          url: '/api/admin/upload_image/',
          params: null,
          fileKey: 'image',
          connectionCount: 3,
          leaveConfirm: this.$t('m.Uploading_is_in_progress')
        },
        allowedStyles: { span: ['color'] }
      }))
      this.editor.setValue(this.modelValue)
      this.editor.on('valuechanged', this.onValueChanged)
      this.editor.on('decorate', this.onValueChanged)
    },
    beforeUnmount () {
      if (this.editor) {
        this.editor.off('valuechanged', this.onValueChanged)
        this.editor.off('decorate', this.onValueChanged)
        this.editor.destroy()
        this.editor = null
      }
    },
    methods: {
      onValueChanged () {
        if (!this.editor || this.updatingValue) return
        const value = this.editor.getValue()
        if (value !== this.modelValue) {
          this.$emit('update:modelValue', value)
          this.$emit('change', value)
        }
      }
    },
    watch: {
      modelValue (value) {
        if (this.editor && this.editor.getValue() !== value) {
          this.updatingValue = true
          this.editor.setValue(value)
          this.updatingValue = false
        }
      }
    }
  }
</script>
