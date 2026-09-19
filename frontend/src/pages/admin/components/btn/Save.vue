<template>
  <el-button type="primary" @click="$emit('click', $event)">{{$t('m.Save')}}</el-button>
</template>
<script>
  export default{
    name: 'Save',
    emits: ['click']
  }
</script>
