<template>
  <Row type="flex" justify="space-around">
    <Col :span="20" id="status">
      <Alert :type="status.type" showIcon>
        <span class="title">{{status.unknown ? '判题状态暂不可识别' : $t('m.' + status.statusName.replace(/ /g, "_"))}}</span>
        <span class="title" v-if="isCE">[main.c:后面的两个数字分别表示错误代码所在的“行号”和“列号”]</span>
        <template #desc><div class="content">
          <template v-if="isCE">
            <!--
            请选择出错信息的语言：
            <i-switch size="large" v-model="isCn">
                <span slot="open">中文</span>
                <span slot="close">English</span>
            </i-switch>
            <pre v-if="isCn">{{submission.statistic_info.err_info_cn}}</pre>
            <pre v-else>{{submission.statistic_info.err_info}}</pre>
            -->
            <pre>{{submission.statistic_info.err_info}}</pre>
          </template>
          <template v-else>
            <span>{{$t('m.Time')}}: {{ $filters.submissionTime(submission.statistic_info.time_cost) }}</span>
            <span>{{$t('m.Memory')}}: {{ $filters.submissionMemory(submission.statistic_info.memory_cost) }}</span>
            <span>{{$t('m.Lang')}}: {{submission.language}}</span>
            <span>{{$t('m.Author')}}: {{submission.username}}</span>
          </template>
        </div></template>
      </Alert>
    </Col>

    <!--后台返info就显示出来， 权限控制放后台 -->
    <Col v-if="submission.info && !isCE" :span="20">
      <Table stripe :loading="loading" :disabled-hover="true" :columns="columns" :data="submission.info.data"></Table>
    </Col>

    <Col v-if="submission.id && !loading" :span="20">
      <SubmissionAnalysis :submission="submission"></SubmissionAnalysis>
    </Col>

    <Col :span="20">
      <Highlight :code="submission.code" :language="submission.language" :border-color="status.color"></Highlight>
    </Col>
    <Col v-if="submission.can_unshare" :span="20">
      <div id="share-btn">
        <Button v-if="submission.shared"
                type="warning" size="large" @click="shareSubmission(false)">
          {{$t('m.UnShare')}}
        </Button>
        <Button v-else
                type="primary" size="large" @click="shareSubmission(true)">
          {{$t('m.Share')}}
        </Button>
      </div>
    </Col>
  </Row>

</template>

<script>
  import { resolveComponent } from 'vue'

  import api from '@oj/api'
  import {JUDGE_STATUS} from '@/utils/constants'
  import utils from '@/utils/utils'
  import Highlight from '@/pages/oj/components/Highlight'
  import SubmissionAnalysis from './SubmissionAnalysis'
  import {isObject, sameId} from './submissionAnalysisData'

  export default {
    name: 'submissionDetails',
    components: {
      Highlight,
      SubmissionAnalysis
    },
    data () {
      return {
        isCn: true,
        columns: [
          {
            title: this.$i18n.t('m.ID'),
            align: 'center',
            type: 'index'
          },
          {
            title: this.$i18n.t('m.Status'),
            align: 'center',
            render: (h, params) => {
              const status = Object.prototype.hasOwnProperty.call(JUDGE_STATUS, params.row.result) ? JUDGE_STATUS[params.row.result] : null
              return h(resolveComponent('Tag'), {

                color: status ? status.color : 'blue'

              }, () => (status ? this.$i18n.t('m.' + status.name.replace(/ /g, '_')) : '状态未知'))
            }
          },
          {
            title: this.$i18n.t('m.Memory'),
            align: 'center',
            render: (h, params) => {
              return h('span', utils.submissionMemoryFormat(params.row.memory))
            }
          },
          {
            title: this.$i18n.t('m.Time'),
            align: 'center',
            render: (h, params) => {
              return h('span', utils.submissionTimeFormat(params.row.cpu_time))
            }
          }
        ],
        submission: {
          result: '0',
          code: '',
          info: {
            data: []
          },
          statistic_info: {
            time_cost: '',
            memory_cost: ''
          }
        },
        isConcat: false,
        loading: false,
        requestSequence: 0
      }
    },
    mounted () {
      this.getSubmission()
    },
    beforeUnmount () {
      this.requestSequence++
    },
    watch: {
      '$route.params.id' () { this.getSubmission() },
      '$store.getters.user.id' () { this.getSubmission() }
    },
    methods: {
      getSubmission () {
        const sequence = ++this.requestSequence
        const id = this.$route.params.id
        const userId = this.$store.getters.user.id
        this.loading = true
        this.submission = {result: null, code: '', statistic_info: {}, info: null}
        this.columns = this.columns.slice(0, 4)
        this.isConcat = false
        api.getSubmission(id).then(res => {
          if (sequence !== this.requestSequence || id !== this.$route.params.id || userId !== this.$store.getters.user.id) return
          this.loading = false
          let data = res.data.data
          if (!isObject(data) || !sameId(data.id, id)) return
          data = Object.assign({}, data, {
            code: typeof data.code === 'string' ? data.code : '',
            statistic_info: isObject(data.statistic_info) ? data.statistic_info : {},
            info: isObject(data.info) && Array.isArray(data.info.data) && data.info.data.every(isObject) ? data.info : null
          })
          if (data.info && data.info.data.length && !this.isConcat) {
            // score exist means the submission is OI problem submission
            if (data.info.data[0].score !== undefined) {
              this.isConcat = true
              const scoreColumn = {
                title: this.$i18n.t('m.Score'),
                align: 'center',
                key: 'score'
              }
              this.columns.push(scoreColumn)
              this.loadingTable = false
            }
            if (this.isAdminRole) {
              this.isConcat = true
              const adminColumn = [
                {
                  title: this.$i18n.t('m.Real_Time'),
                  align: 'center',
                  render: (h, params) => {
                    return h('span', utils.submissionTimeFormat(params.row.real_time))
                  }
                },
                {
                  title: this.$i18n.t('m.Signal'),
                  align: 'center',
                  key: 'signal'
                }
              ]
              this.columns = this.columns.concat(adminColumn)
            }
          }
          this.submission = data
        }, () => {
          if (sequence === this.requestSequence) this.loading = false
        })
      },
      shareSubmission (shared) {
        let data = {id: this.submission.id, shared: shared}
        api.updateSubmission(data).then(res => {
          this.getSubmission()
          this.$success(this.$i18n.t('m.Succeeded'))
        }, () => {
        })
      }
    },
    computed: {
      status () {
        const status = Object.prototype.hasOwnProperty.call(JUDGE_STATUS, this.submission.result) ? JUDGE_STATUS[this.submission.result] : null
        if (!status) return {type: 'info', statusName: '', color: 'blue', unknown: true}
        return {
          type: status.type,
          statusName: status.name,
          color: status.color
        }
      },
      isCE () {
        return this.submission.result === -2
      },
      isAdminRole () {
        return this.$store.getters.isAdminRole
      }
    }
  }
</script>

<style scoped lang="less">
  #status {
    .title {
      font-size: 20px;
    }
    .content {
      margin-top: 10px;
      font-size: 14px;
      span {
        margin-right: 10px;
      }
      pre {
        white-space: pre-wrap;
        word-wrap: break-word;
        word-break: break-all;
      }
    }
  }

  .admin-info {
    margin: 5px 0;
    &-content {
      font-size: 16px;
      padding: 10px;
    }
  }

  #share-btn {
    float: right;
    margin-top: 5px;
    margin-right: 10px;
  }

  pre {
    border: none;
    background: none;
  }
</style>
