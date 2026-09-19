<template>
  <li @click.stop="handleClick" :class="{disabled: disabled}">
    <slot></slot>
  </li>
</template>

<script>

  export default {
    name: 'VerticalMenu-item',
    inject: { selectVerticalMenu: { default: null } },
    props: {
      route: {
        type: [String, Object]
      },
      disabled: {
        type: Boolean,
        default: false
      }
    },
    methods: {
      handleClick () {
        if (this.route) {
          if (!this.disabled && this.selectVerticalMenu) this.selectVerticalMenu(this.route)
        }
      }
    }
  }
</script>

<style scoped lang="less">
  .disabled {
    /*background-color: #ccc;*/
    opacity: 1;
    /*cursor: not-allowed;*/
    pointer-events: none;
    color: #ccc;
    &:hover {
      border-left: none;
      color: #ccc;
      background: #fff;
    }
  }

  li {
    border-bottom: 1px dashed #e9eaec;
    color: #495060;
    display: block;
    text-align: left;
    padding: 15px 20px;
    &:hover {
      background: #f8f8f9;
      border-left: 2px solid #5cadff;
      color: #2d8cf0;
    }
    & > .ivu-icon {
      font-size: 16px;
      margin-right: 8px;
    }
    &:last-child {
      border-bottom: none;
    }
  }
</style>
