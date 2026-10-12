<template>
  <div class="setting-main">
    <p class="section-title">{{$t('m.Sessions')}}</p>
    <div class="flex-container setting-content">
      <template v-for="session in sessions" :key="session.session_key">
        <Card :padding="20" class="flex-child">
          <template #title><span style="line-height: 20px">{{session.ip}}</span></template>
          <template #extra><div>
            <Tag v-if="session.current_session" color="green">{{$t('m.Current')}}</Tag>
            <Button v-else
                    type="warning"
                    size="small"
                    @click="deleteSession(session.session_key)">{{$t('m.Revoke')}}
            </Button>
          </div></template>
          <Form :label-width="100">
            <FormItem label="OS :" class="item">
              {{ platform(session.user_agent) }}
            </FormItem>
            <FormItem label="Browser :" class="item">
              {{ browser(session.user_agent) }}
            </FormItem>
            <FormItem label="Last Activity :" class="item">
              {{ $filters.localtime(session.last_activity) }}
            </FormItem>
          </Form>
        </Card>
      </template>
    </div>

    <p class="section-title">{{$t('m.Two_Factor_Authentication')}}</p>
    <div class="mini-container setting-content">
      <Form>
        <Alert v-if="TFAOpened"
               type="success"
               class="notice"
               showIcon>{{$t('m.You_have_enabled_two_factor_authentication')}}
        </Alert>
        <FormItem v-if="!TFAOpened">
          <div class="oj-relative">
            <img :src="qrcodeSrc" id="qr-img">
            <Spin size="large" fix v-if="loadingQRcode"></Spin>
          </div>
        </FormItem>
        <template v-if="!loadingQRcode">
          <FormItem style="width: 250px">
            <Input v-model="formTwoFactor.code" :placeholder="$t('m.Enter_the_code_from_your_application')"/>
          </FormItem>
          <Button type="primary"
                  :loading="loadingBtn"
                  @click="updateTFA(false)"
                  v-if="!TFAOpened">{{$t('m.Open_TFA')}}
          </Button>
          <Button type="error"
                  :loading="loadingBtn"
                  @click="closeTFA"
                  v-else>{{$t('m.Close_TFA')}}
          </Button>
        </template>
      </Form>
    </div>
  </div>
</template>

<script>
  import api from '@oj/api'
  import {mapGetters, mapActions} from 'vuex'
  import browserDetector from 'browser-detect'

  const browsers = {}
  const loadBrowser = (userAgent) => {
    let browser = {}
    if (userAgent in Object.keys(browsers)) {
      browser = browsers[userAgent]
    } else {
      browser = browserDetector(userAgent)
      browsers[userAgent] = browser
    }
    return browser
  }

  export default {
    data () {
      return {
        qrcodeSrc: '',
        loadingQRcode: false,
        loadingBtn: false,
        securityEpoch: 0,
        securityAlive: true,
        securityAccountId: null,
        securityTFAOpened: false,
        formTwoFactor: {
          code: ''
        },
        sessions: []
      }
    },
    watch: {
      securityIdentity: {
        immediate: true,
        handler () {
          this.securityEpoch++
          this.securityAccountId = this.user.id == null ? null : String(this.user.id)
          this.securityTFAOpened = !!this.user.two_factor_auth
          this.sessions = []
          this.qrcodeSrc = ''
          this.formTwoFactor.code = ''
          this.loadingQRcode = false
          this.loadingBtn = false
          if (!this.user.id) return
          this.getSessions()
          if (!this.TFAOpened) this.getAuthImg()
        }
      }
    },
    beforeUnmount () {
      this.securityAlive = false
      this.securityEpoch++
    },
    methods: {
      currentSecurity (epoch) {
        const user = this.$store.getters.user
        const accountId = user.id == null ? null : String(user.id)
        return this.securityAlive && epoch === this.securityEpoch && accountId !== null &&
          accountId === this.securityAccountId && !!user.two_factor_auth === this.securityTFAOpened
      },
      browser (value) {
        let b = loadBrowser(value)
        if (b.name && b.version) {
          return b.name + ' ' + b.version
        } else {
          return 'Unknown'
        }
      },
      platform (value) {
        let b = loadBrowser(value)
        return b.os ? b.os : 'Unknown'
      },

      ...mapActions(['getProfile']),
      getAuthImg () {
        const epoch = this.securityEpoch
        if (!this.currentSecurity(epoch) || this.TFAOpened) return
        this.loadingQRcode = true
        api.twoFactorAuth('get').then(res => {
          if (!this.currentSecurity(epoch)) return
          this.loadingQRcode = false
          this.qrcodeSrc = res.data.data
        }).catch(() => {
          if (this.currentSecurity(epoch)) this.loadingQRcode = false
        })
      },
      getSessions () {
        const epoch = this.securityEpoch
        if (!this.currentSecurity(epoch)) return
        api.getSessions().then(res => {
          if (!this.currentSecurity(epoch)) return
          let data = res.data.data
          // 将当前session放到第一个
          let sessions = data.filter(session => {
            return session.current_session
          })
          data.forEach(session => {
            if (!session.current_session) {
              sessions.push(session)
            }
          })
          this.sessions = sessions
        }).catch(() => {})
      },
      deleteSession (sessionKey) {
        const epoch = this.securityEpoch
        this.$Modal.confirm({
          title: 'Confirm',
          content: 'Are you sure to revoke the session?',
          onOk: () => {
            if (!this.currentSecurity(epoch)) return
            api.deleteSession(sessionKey).then(res => {
              if (this.currentSecurity(epoch)) this.getSessions()
            }, _ => {
            })
          }
        })
      },
      closeTFA () {
        const epoch = this.securityEpoch
        this.$Modal.confirm({
          title: 'Confirm',
          content: 'Two-factor Authentication is a powerful tool to protect your account, are you sure to close it?',
          onOk: () => {
            if (this.currentSecurity(epoch)) this.updateTFA(true)
          }
        })
      },
      updateTFA (close) {
        const epoch = this.securityEpoch
        if (!this.currentSecurity(epoch)) return
        let method = close === false ? 'post' : 'put'
        this.loadingBtn = true
        api.twoFactorAuth(method, this.formTwoFactor).then(res => {
          if (!this.currentSecurity(epoch)) return
          this.loadingBtn = false
          this.getProfile()
          this.formTwoFactor.code = ''
        }, err => {
          if (!this.currentSecurity(epoch)) return
          this.formTwoFactor.code = ''
          this.loadingBtn = false
          const message = err && err.data && err.data.data
          if (typeof message === 'string' && message.indexOf('session') > -1) {
            this.getProfile()
            this.getAuthImg()
          }
        })
      }
    },
    computed: {
      ...mapGetters(['user']),
      securityIdentity () { return JSON.stringify([this.user.id || null, !!this.user.two_factor_auth]) },
      TFAOpened () {
        return this.user && this.user.two_factor_auth
      }
    }
  }
</script>

<style lang="less" scoped>
  .notice {
    font-size: 16px;
    margin-bottom: 20px;
    display: inline-block;
  }

  .oj-relative {
    width: 150px;
    #qr-img {
      width: 300px;
      margin: -10px 0 -30px -20px;
    }
  }

  .flex-container {
    flex-flow: row wrap;
    justify-content: flex-start;
    .flex-child {
      flex: 1 0;
      max-width: 350px;
      margin-right: 30px;
      margin-bottom: 30px;
      .item {
        margin-bottom: 0;
      }
    }
  }
</style>
