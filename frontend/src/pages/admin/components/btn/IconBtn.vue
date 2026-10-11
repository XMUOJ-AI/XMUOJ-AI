<template>
  <div style="display: inline-block;">
    <el-tooltip class="item" effect="dark" :content="name" placement="top">
      <el-button plain size="small" class="legacy-mini legacy-icon-button" :aria-label="name" @click="$emit('click', $event)">
        <template #icon><i :class="'el-icon-fa-' + icon" aria-hidden="true"></i></template>
      </el-button>
    </el-tooltip>
  </div>
</template>

<script>
  export default {
    name: 'IconBtn',
    emits: ['click'],
    props: {
      name: {
        type: String,
        required: true
      },
      icon: {
        type: String,
        required: true
      }
    }
  }
</script>
