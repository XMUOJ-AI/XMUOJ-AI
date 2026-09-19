<template>
  <el-button plain type="primary" @click="$emit('click', $event)">{{$t('m.Cancel')}}</el-button>
</template>
<script>
  export default{
    name: 'Cancel',
    emits: ['click']
  }
</script>
