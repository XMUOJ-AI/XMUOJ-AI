<template>
  <button :type="htmlType" :class="classes" :disabled="disabled" @click="handleClick">
    <Icon v-if="loading" class="ivu-load-loop" type="load-c" />
    <Icon v-else-if="icon" :type="icon" />
    <span v-if="$slots.default"><slot /></span>
  </button>
</template>
<script>
  export default {
    name: 'LegacyButton',
    props: {
      type: String,
      shape: String,
      size: String,
      loading: Boolean,
      disabled: Boolean,
      htmlType: { type: String, default: 'button' },
      icon: String,
      long: Boolean
    },
    emits: ['click'],
    computed: {
      classes () {
        return ['ivu-btn', {
          [`ivu-btn-${this.type}`]: !!this.type,
          [`ivu-btn-${this.shape}`]: !!this.shape,
          [`ivu-btn-${this.size}`]: !!this.size,
          'ivu-btn-long': this.long,
          'ivu-btn-loading': this.loading,
          'ivu-btn-icon-only': !this.$slots.default && (this.icon || this.loading)
        }]
      }
    },
    methods: {
      handleClick (event) {
        if (!this.disabled && !this.loading) this.$emit('click', event)
      }
    }
  }
</script>
