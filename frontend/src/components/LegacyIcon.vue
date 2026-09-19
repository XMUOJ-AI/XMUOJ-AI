<template><i :class="iconClass" :style="iconStyle" aria-hidden="true"></i></template>
<script>
export default {
  name: 'LegacyIcon',
  props: { type: { type: String, default: '' }, size: [String, Number], color: String },
  computed: {
    iconClass () { return this.type.startsWith('el-icon-') ? this.type : ['ivu-icon', 'legacy-icon-ion', 'legacy-icon-ion-' + this.type] },
    iconStyle () { return { fontSize: this.size ? this.size + 'px' : undefined, color: this.color } }
  }
}
</script>
