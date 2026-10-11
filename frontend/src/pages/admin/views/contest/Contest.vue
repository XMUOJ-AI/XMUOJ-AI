<template>
  <div class="view">
    <Panel :title="title">
      <el-form label-position="top">
        <el-row :gutter="20">
          <el-col :span="24">
            <el-form-item :label="$t('m.ContestTitle')" required>
              <el-input v-model="contest.title" :placeholder="$t('m.ContestTitle')"></el-input>
            </el-form-item>
          </el-col>
          <el-col :span="24">
            <el-form-item :label="$t('m.ContestDescription')" required>
              <Simditor v-model="contest.description"></Simditor>
            </el-form-item>
          </el-col>
          <el-col :span="8">
            <el-form-item :label="$t('m.Contest_Start_Time')" required>
              <el-date-picker
                v-model="contest.start_time"
                type="datetime"
                :placeholder="$t('m.Contest_Start_Time')">
              </el-date-picker>
            </el-form-item>
          </el-col>
          <el-col :span="8">
            <el-form-item :label="$t('m.Contest_End_Time')" required>
              <el-date-picker
                v-model="contest.end_time"
                type="datetime"
                :placeholder="$t('m.Contest_End_Time')">
              </el-date-picker>
            </el-form-item>
          </el-col>
          <el-col :span="8">
            <el-form-item :label="$t('m.Contest_Password')">
              <el-input v-model="contest.password" :placeholder="$t('m.Contest_Password')"></el-input>
            </el-form-item>
          </el-col>
          <el-col :span="8">
            <el-form-item :label="$t('m.Contest_Rule_Type')">
              <el-radio class="radio" v-model="contest.rule_type" value="ACM" :disabled="disableRuleType">ACM</el-radio>
              <el-radio class="radio" v-model="contest.rule_type" value="OI" :disabled="disableRuleType">OI</el-radio>
            </el-form-item>
          </el-col>
          <el-col :span="8">
            <el-form-item :label="$t('m.Real_Time_Rank')">
              <el-switch style="--el-switch-on-color: #13ce66; --el-switch-off-color: #ff4949"
                v-model="contest.real_time_rank">
              </el-switch>
            </el-form-item>
          </el-col>
          <el-col :span="8">
            <el-form-item :label="$t('m.Contest_Status')">
              <el-switch
                v-model="contest.visible"
                active-text=""
                inactive-text="">
              </el-switch>
            </el-form-item>
          </el-col>
          <el-col :span="8">
            <el-form-item :label="$t('m.Exam_Mode')">
              <el-switch style="--el-switch-on-color: #ff4949; --el-switch-off-color: #13ce66" v-model="contest.is_exam">
              </el-switch>
              <span style="font-size:12px;color:#999;margin-left:8px">{{ $t('m.Exam_Mode_Desc') }}</span>
            </el-form-item>
          </el-col>
          <el-col :span="24">
            <el-form-item :label="$t('m.Allowed_IP_Ranges')">
              <div v-for="(range, index) in contest.allowed_ip_ranges" :key="index">
                <el-row :gutter="20" style="margin-bottom: 15px">
                  <el-col :span="8">
                    <el-input v-model="range.value" :placeholder="$t('m.CIDR_Network')"></el-input>
                  </el-col>
                  <el-col :span="10">
                    <el-button plain @click="addIPRange"><template #icon><i class="el-icon-fa-plus" aria-hidden="true"></i></template></el-button>
                    <el-button plain @click="removeIPRange(range)"><template #icon><i class="el-icon-fa-trash" aria-hidden="true"></i></template></el-button>
                  </el-col>
                </el-row>
              </div>
            </el-form-item>
          </el-col>
        </el-row>
      </el-form>
      <save @click="saveContest"></save>
    </Panel>
  </div>
</template>

<script>
  import api from '../../api.js'
  import Simditor from '../../components/Simditor.vue'

  export default {
    name: 'CreateContest',
    components: {
      Simditor
    },
    data () {
      return {
        title: 'Create Contest',
        disableRuleType: false,
        contest: {
          title: '',
          description: '',
          start_time: '',
          end_time: '',
          rule_type: 'ACM',
          password: '',
          real_time_rank: true,
          visible: true,
          is_exam: false,
          allowed_ip_ranges: [{
            value: ''
          }]
        }
      }
    },
    methods: {
      saveContest () {
        let funcName = this.$route.name === 'edit-contest' ? 'editContest' : 'createContest'
        let data = Object.assign({}, this.contest)
        let ranges = []
        for (let v of data.allowed_ip_ranges) {
          if (v.value !== '') {
            ranges.push(v.value)
          }
        }
        data.allowed_ip_ranges = ranges
        api[funcName](data).then(res => {
          this.$router.push({name: 'contest-list', query: {refresh: 'true'}})
        }).catch(() => {
        })
      },
      addIPRange () {
        this.contest.allowed_ip_ranges.push({value: ''})
      },
      removeIPRange (range) {
        let index = this.contest.allowed_ip_ranges.indexOf(range)
        if (index !== -1) {
          this.contest.allowed_ip_ranges.splice(index, 1)
        }
      }
    },
    mounted () {
      if (this.$route.name === 'edit-contest') {
        this.title = 'Edit Contest'
        this.disableRuleType = false
        api.getContest(this.$route.params.contestId).then(res => {
          let data = res.data.data
          let ranges = []
          for (let v of data.allowed_ip_ranges) {
            ranges.push({value: v})
          }
          if (ranges.length === 0) {
            ranges.push({value: ''})
          }
          data.allowed_ip_ranges = ranges
          this.contest = data
        }).catch(() => {
        })
      }
    }
  }
</script>
