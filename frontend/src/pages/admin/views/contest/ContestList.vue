<template>
  <div class="view">
    <Panel title="Contest List">
      <template #header><div style="display:flex;gap:8px;">
        <el-input
          v-model="ownerKeyword"
          placeholder="Search by owner"
          style="width:180px;"><template #prefix><i class="el-icon-user" aria-hidden="true"></i></template>
        </el-input>
        <el-input
          v-model="keyword"
          placeholder="Search by title"><template #prefix><i class="el-icon-search" aria-hidden="true"></i></template>
        </el-input>
      </div></template>
      <el-table
        v-loading="loading"
        element-loading-text="loading"
        ref="table"
        :data="contestList"
        style="width: 100%">
        <el-table-column type="expand">
          <template #default="props">
            <p>Start Time: {{$filters.localtime(props.row.start_time)}}</p>
            <p>End Time: {{$filters.localtime(props.row.end_time)}}</p>
            <p>Create Time: {{$filters.localtime(props.row.create_time)}}</p>
            <p>Creator: {{props.row.created_by.username}}</p>
          </template>
        </el-table-column>
        <el-table-column
          prop="id"
          width="80"
          label="ID">
        </el-table-column>
        <el-table-column
          prop="title"
          label="Title">
        </el-table-column>
        <el-table-column
          label="Owner"
          width="140">
          <template #default="scope">
            {{ scope.row.created_by.username }}
          </template>
        </el-table-column>
        <el-table-column
          label="Rule Type"
          width="130">
          <template #default="scope">
            <el-tag>{{scope.row.rule_type}}</el-tag>
          </template>
        </el-table-column>
        <el-table-column
          label="Contest Type"
          width="180">
          <template #default="scope">
            <el-tag :type="scope.row.contest_type === 'Public' ? 'success' : 'primary'">
              {{ scope.row.contest_type}}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column
          label="Status"
          width="130">
          <template #default="scope">
            <el-tag
              :type="scope.row.status === '-1' ? 'danger' : scope.row.status === '0' ? 'success' : 'primary'">
              {{contestStatus(scope.row.status)}}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column
          width="100"
          label="Visible">
          <template #default="scope">
            <el-switch v-model="scope.row.visible"
                       active-text=""
                       inactive-text=""
                       @change="handleVisibleSwitch(scope.row)">
            </el-switch>
          </template>
        </el-table-column>
        <el-table-column
          fixed="right"
          width="360"
          label="Operation">
          <template #default="scope"><div>
            <icon-btn name="Edit" icon="edit" @click="goEdit(scope.row.id)"></icon-btn>
            <icon-btn name="Problem" icon="list-ol" @click="goContestProblemList(scope.row.id)"></icon-btn>
            <icon-btn name="Announcement" icon="info-circle"
                      @click="goContestAnnouncement(scope.row.id)"></icon-btn>
            <icon-btn icon="download" name="Download Accepted Submissions"
                      @click="openDownloadOptions(scope.row.id, 1)"></icon-btn>
            <icon-btn icon="download" name="Download All Submissions"
                      @click="openDownloadOptions(scope.row.id, 0)"></icon-btn>
            <icon-btn icon="trash" name="Delete"
                      @click="deleteContest(scope.row)"></icon-btn>
          </div></template>
        </el-table-column>
      </el-table>
      <div class="panel-options">
        <el-pagination
          class="page"
          layout="prev, pager, next, sizes"
          @current-change="currentChange"
          @size-change="handlePageSizeChange"
          v-model:current-page="currentPage"
          :page-size="pageSize"
          :page-sizes="pageSizes"
          :total="total">
        </el-pagination>
      </div>
    </Panel>
    <el-dialog title="Download Contest Submissions"
               width="30%"
               v-model="downloadDialogVisible">
      <el-switch v-model="excludeAdmin" active-text="Exclude admin submissions"></el-switch>
      <template #footer><span class="dialog-footer">
        <el-button type="primary" @click="downloadSubmissions">确 定</el-button>
      </span></template>
    </el-dialog>
  </div>
</template>

<script>
  import api from '../../api.js'
  import utils from '@/utils/utils'
  import {CONTEST_STATUS_REVERSE} from '@/utils/constants'

  export default {
    name: 'ContestList',
    data () {
      return {
        pageSize: 15,
        pageSizes: [10, 15, 30, 50, 100, 200],
        total: 0,
        contestList: [],
        keyword: '',
        ownerKeyword: '',
        loading: false,
        excludeAdmin: true,
        currentPage: 1,
        currentId: 1,
        dlType: 0,
        downloadDialogVisible: false,
        syncingRouteState: false
      }
    },
    mounted () {
      this.applyRouteState(this.$route)
      this.getContestList(this.currentPage, false)
    },
    methods: {
      contestStatus (value) {
        return CONTEST_STATUS_REVERSE[value].name
      },
      applyRouteState (route) {
        const query = route.query || {}
        const parsedPage = parseInt(query.page)
        const parsedPageSize = parseInt(query.page_size)

        this.syncingRouteState = true
        this.keyword = query.keyword || ''
        this.ownerKeyword = query.owner || ''
        this.currentPage = Number.isInteger(parsedPage) && parsedPage > 0 ? parsedPage : 1
        this.pageSize = this.pageSizes.includes(parsedPageSize) ? parsedPageSize : 15
        this.syncingRouteState = false
      },
      syncRouteQuery () {
        const query = {}
        if (this.keyword) {
          query.keyword = this.keyword
        }
        if (this.ownerKeyword) {
          query.owner = this.ownerKeyword
        }
        if (this.currentPage > 1) {
          query.page = String(this.currentPage)
        }
        if (this.pageSize !== 15) {
          query.page_size = String(this.pageSize)
        }

        const currentQuery = this.$route.query || {}
        const queryUnchanged = currentQuery.keyword === query.keyword &&
          currentQuery.owner === query.owner &&
          currentQuery.page === query.page &&
          currentQuery.page_size === query.page_size &&
          Object.keys(currentQuery).length === Object.keys(query).length

        if (queryUnchanged) {
          return
        }

        this.$router.replace({
          name: this.$route.name,
          params: this.$route.params,
          query
        }).catch(() => {})
      },
      // 切换页码回调
      currentChange (page) {
        this.currentPage = page
        this.getContestList(page)
      },
      handlePageSizeChange (pageSize) {
        this.pageSize = pageSize
        this.currentPage = 1
        this.getContestList(1)
      },
      getContestList (page, syncRoute = true) {
        this.currentPage = page
        if (syncRoute) {
          this.syncRouteQuery()
        }
        this.loading = true
        api.getContestList((page - 1) * this.pageSize, this.pageSize, this.keyword, this.ownerKeyword).then(res => {
          this.loading = false
          this.total = res.data.data.total
          this.contestList = res.data.data.results
        }, res => {
          this.loading = false
        })
      },
      openDownloadOptions (contestId, dlType) {
        this.downloadDialogVisible = true
        this.currentId = contestId
        this.dlType = dlType
      },
      downloadSubmissions () {
        let excludeAdmin = this.excludeAdmin ? '1' : '0'
        let url = `/admin/download_submissions?contest_id=${this.currentId}&exclude_admin=${excludeAdmin}&dlType=${this.dlType}`
        utils.downloadFile(url)
      },
      goEdit (contestId) {
        this.$router.push({name: 'edit-contest', params: {contestId}})
      },
      goContestAnnouncement (contestId) {
        this.$router.push({name: 'contest-announcement', params: {contestId}})
      },
      goContestProblemList (contestId) {
        this.$router.push({name: 'contest-problem-list', params: {contestId}})
      },
      deleteContest (row) {
        this.$confirm(
          'Hard delete will permanently remove this contest and related data (submissions/ranks). Continue?',
          'Warning',
          {
            type: 'warning'
          }
        ).then(() => {
          this.loading = true
          api.deleteContest(row.id, true).then(() => {
            this.$success('Contest deleted successfully')
            this.getContestList(this.currentPage)
          }).catch((err) => {
            const message = err && err.data && err.data.data
              ? err.data.data
              : 'Delete failed. Please check owner permission or contest status and try again.'
            this.$error(message)
          }).finally(() => {
            this.loading = false
          })
        }).catch(() => {})
      },
      handleVisibleSwitch (row) {
        api.editContest(row)
      }
    },
    watch: {
      '$route' (newVal) {
        this.applyRouteState(newVal)
        this.getContestList(this.currentPage, false)
      },
      'keyword' () {
        if (this.syncingRouteState) {
          return
        }
        this.currentChange(1)
      },
      'ownerKeyword' () {
        if (this.syncingRouteState) {
          return
        }
        this.currentChange(1)
      }
    }
  }
</script>
