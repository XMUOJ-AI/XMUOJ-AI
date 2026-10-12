<template>
  <Card :padding="0" dis-hover>
    <ul>
      <slot></slot>
    </ul>
  </Card>
</template>

<script>
  export default {
    name: 'VerticalMenu',
    emits: ['on-click'],
    provide () { return { selectVerticalMenu: route => this.$emit('on-click', route) } }
  }
</script>

<style scoped lang="less">
</style>
