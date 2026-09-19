<template>
  <div class="view">
    <Panel :title="$t('m.User_User') ">
      <template #header><div>
        <el-row :gutter="20">
          <el-col :span="8">
            <el-button v-show="selectedUsers.length"
                       type="warning"
                       @click="deleteUsers(selectedUserIDs)"><template #icon><i class="el-icon-fa-trash" aria-hidden="true"></i></template>Delete
            </el-button>
          </el-col>
          <el-col :span="selectedUsers.length ? 16: 24">
            <el-input v-model="keyword" placeholder="Keywords"><template #prefix><i class="el-icon-search" aria-hidden="true"></i></template></el-input>
          </el-col>
        </el-row>
      </div></template>
      <el-table
        v-loading="loadingTable"
        element-loading-text="loading"
        @selection-change="handleSelectionChange"
        ref="table"
        :data="userList"
        style="width: 100%">
        <el-table-column type="selection" width="55"></el-table-column>

        <el-table-column prop="id" label="ID"></el-table-column>

        <el-table-column prop="username" label="Username"></el-table-column>

        <el-table-column prop="create_time" label="Create Time">
          <template #default="scope">
            {{$filters.localtime(scope.row.create_time)}}
          </template>
        </el-table-column>

        <el-table-column prop="last_login" label="Last Login">
          <template #default="scope">
            {{$filters.localtime(scope.row.last_login)}}
          </template>
        </el-table-column>

        <el-table-column prop="real_name" label="Real Name"></el-table-column>

        <el-table-column prop="school" label="Class Name"></el-table-column>

        <el-table-column prop="admin_type" label="User Type">
          <template #default="scope">
            {{ scope.row.admin_type }}
          </template>
        </el-table-column>

        <el-table-column fixed="right" label="Option" width="200">
          <template #default="{row}">
            <icon-btn name="Edit" icon="edit" @click="openUserDialog(row.id)"></icon-btn>
            <icon-btn name="Delete" icon="trash" @click="deleteUsers([row.id])"></icon-btn>
          </template>
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

    <Panel>
      <template #title><span>{{$t('m.Import_User')}}
        <el-popover placement="right" trigger="hover">
          <p>仅支持逗号分隔的、Unicode编码的csv文件。<br />每个用户一行，分别为：学号,姓名,班级<br />若用户已存在，仅更新班级信息，其余不变；否则按照默认密码123456新建用户。</p>
          <template #reference><i class="el-icon-fa-question-circle import-user-icon"></i></template>
        </el-popover>
      </span></template>
      <el-upload v-if="!uploadUsers.length"
                 action=""
                 :show-file-list="false"
                 accept=".csv"
                 :before-upload="handleUsersCSV">
        <el-button size="small" type="primary"><template #icon><i class="el-icon-fa-upload" aria-hidden="true"></i></template>Choose File</el-button>
      </el-upload>
      <template v-else>
        <el-table :data="uploadUsersPage">
          <el-table-column label="Username">
            <template #default="{row}">
              {{row[0]}}
            </template>
          </el-table-column>
          <el-table-column label="Real Name">
            <template #default="{row}">
              {{row[1]}}
            </template>
          </el-table-column>
          <el-table-column label="Class Name">
            <template #default="{row}">
              {{row[2]}}
            </template>
          </el-table-column>
        </el-table>
        <div class="panel-options">
          <el-button type="primary" size="small"
                     @click="handleUsersUpload"><template #icon><i class="el-icon-fa-upload" aria-hidden="true"></i></template>Import All
          </el-button>
          <el-button type="warning" size="small"
                     @click="handleResetData"><template #icon><i class="el-icon-fa-undo" aria-hidden="true"></i></template>Reset Data
          </el-button>
          <el-pagination
            class="page"
            layout="prev, pager, next"
            :page-size="uploadUsersPageSize"
            v-model:current-page="uploadUsersCurrentPage"
            :total="uploadUsers.length">
          </el-pagination>
        </div>
      </template>
    </Panel>

    <Panel :title="$t('m.Generate_User')">
      <el-form :model="formGenerateUser" ref="formGenerateUser">
        <el-row type="flex" justify="space-between">
          <el-col :span="4">
            <el-form-item label="Prefix" prop="prefix">
              <el-input v-model="formGenerateUser.prefix" placeholder="Prefix"></el-input>
            </el-form-item>
          </el-col>
          <el-col :span="4">
            <el-form-item label="Suffix" prop="suffix">
              <el-input v-model="formGenerateUser.suffix" placeholder="Suffix"></el-input>
            </el-form-item>
          </el-col>
          <el-col :span="4">
            <el-form-item label="Start Number" prop="number_from" required>
              <el-input-number v-model="formGenerateUser.number_from" style="width: 100%"></el-input-number>
            </el-form-item>
          </el-col>
          <el-col :span="4">
            <el-form-item label="End Number" prop="number_to" required>
              <el-input-number v-model="formGenerateUser.number_to" style="width: 100%"></el-input-number>
            </el-form-item>
          </el-col>
          <el-col :span="4">
            <el-form-item label="Password Length" prop="password_length" required>
              <el-input v-model="formGenerateUser.password_length"
                        placeholder="Password Length"></el-input>
            </el-form-item>
          </el-col>
        </el-row>

        <el-form-item>
          <el-button type="primary" @click="generateUser" :loading="loadingGenerate"><template #icon><i class="el-icon-fa-users" aria-hidden="true"></i></template>Generate & Export
          </el-button>
          <span class="userPreview" v-if="formGenerateUser.number_from && formGenerateUser.number_to &&
                                          formGenerateUser.number_from <= formGenerateUser.number_to">
            The usernames will be {{formGenerateUser.prefix + formGenerateUser.number_from + formGenerateUser.suffix}},
            <span v-if="formGenerateUser.number_from + 1 < formGenerateUser.number_to">
              {{formGenerateUser.prefix + (formGenerateUser.number_from + 1) + formGenerateUser.suffix + '...'}}
            </span>
            <span v-if="formGenerateUser.number_from + 1 <= formGenerateUser.number_to">
              {{formGenerateUser.prefix + formGenerateUser.number_to + formGenerateUser.suffix}}
            </span>
          </span>
        </el-form-item>
      </el-form>
    </Panel>

    <Panel :title="$t('m.User_New_Password')">
      <el-form :model="formChangeUserpassword" ref="formChangeUserpassword">
        <el-row type="flex" justify="space-between">
          <el-col :span="4">
            <el-form-item :label="formChangeUserpassword.match_type === 'type_exact_list' ? '学号列表' : '目标特征串'" prop="target_name" required>
              <el-input v-if="formChangeUserpassword.match_type !== 'type_exact_list'" v-model="formChangeUserpassword.target_name" style="width: 100%"></el-input>
              <el-input v-else v-model="formChangeUserpassword.target_name" type="textarea" :rows="3" placeholder="学号，一行一个或逗号分隔" style="width: 100%"></el-input>
            </el-form-item>
          </el-col>
          <el-col :span="4">
            <el-form-item label="筛选方式">
              <el-select size="small" v-model="formChangeUserpassword.match_type">
                <el-option label="匹配班级名" value="type_schoolname"></el-option>
                <el-option label="匹配用户名" value="type_username"></el-option>
                <el-option label="精确学号列表" value="type_exact_list"></el-option>
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="4">
            <el-form-item :label="formChangeUserpassword.match_type === 'type_exact_list' ? '学号后几位' : '学号后几位'" prop="right_length">
              <el-input-number v-model="formChangeUserpassword.right_length" style="width: 100%" :disabled="formChangeUserpassword.match_type === 'type_exact_list'"></el-input-number>
            </el-form-item>
          </el-col>
          <el-col :span="4">
            <el-form-item :label="formChangeUserpassword.match_type === 'type_exact_list' ? '后缀/random' : '后缀'" prop="suffix" required>
              <el-input v-model="formChangeUserpassword.suffix" style="width: 100%" :placeholder="formChangeUserpassword.match_type === 'type_exact_list' ? '填 random 生成随机密码' : ''"></el-input>
            </el-form-item>
          </el-col>
          <el-col :span="4">
            <el-form-item :label="formChangeUserpassword.match_type === 'type_exact_list' ? '新密码规则' : '新密码 = 学号后几位 + 后缀'">
              <span v-if="formChangeUserpassword.match_type === 'type_exact_list'" style="font-size:12px;color:#909399">填 random=随机8位<br/>填其他=固定后缀</span>
              <br /><el-button type="primary" @click="changeUserpassword" :loading="loadingChangeUserpassword"><template #icon><i class="el-icon-fa-users" aria-hidden="true"></i></template>批量修改密码</el-button>
            </el-form-item>
          </el-col>
        </el-row>        
      </el-form>
    </Panel>

    <!--对话框-->
    <el-dialog :title="$t('m.User_Info')" v-model="showUserDialog" :close-on-click-modal="false">
      <el-form :model="user" label-width="120px" label-position="left">
        <el-row :gutter="20">
          <el-col :span="12">
            <el-form-item :label="$t('m.User_Username')" required>
              <el-input v-model="user.username"></el-input>
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item :label="$t('m.User_Real_Name')" required>
              <el-input v-model="user.real_name"></el-input>
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item :label="$t('m.User_Email')">
              <el-input v-model="user.email"></el-input>
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item :label="$t('m.User_New_Password')">
              <el-input v-model="user.password"></el-input>
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item :label="$t('m.User_Type')">
              <el-select v-model="user.admin_type">
                <el-option label="Regular User" value="Regular User"></el-option>
                <el-option label="Admin" value="Admin"></el-option>
                <el-option label="Super Admin" value="Super Admin"></el-option>
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item :label="$t('m.Problem_Permission')">
              <el-select v-model="user.problem_permission" :disabled="user.admin_type!=='Admin'">
                <el-option label="None" value="None"></el-option>
                <el-option label="Own" value="Own"></el-option>
                <el-option label="All" value="All"></el-option>
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="8">
            <el-form-item :label="$t('m.Two_Factor_Auth')">
              <el-switch style="--el-switch-on-color: #13ce66; --el-switch-off-color: #ff4949"
                v-model="user.two_factor_auth"
                :disabled="!user.real_tfa">
              </el-switch>
            </el-form-item>
          </el-col>
          <el-col :span="8">
            <el-form-item label="Open Api">
              <el-switch style="--el-switch-on-color: #13ce66; --el-switch-off-color: #ff4949"
                v-model="user.open_api">
              </el-switch>
            </el-form-item>
          </el-col>
          <el-col :span="8">
            <el-form-item :label="$t('m.Is_Disabled')">
              <el-switch
                v-model="user.is_disabled">
              </el-switch>
            </el-form-item>
          </el-col>
        </el-row>
      </el-form>
      <template #footer><span class="dialog-footer">
        <cancel @click="showUserDialog = false">Cancel</cancel>
        <save @click="saveUser()"></save>
      </span></template>
    </el-dialog>
  </div>
</template>

<script>
  import papa from 'papaparse'
  import api from '../../api.js'
  import utils from '@/utils/utils'

  export default {
    name: 'User',
    data () {
      return {
        // 一页显示的用户数
        pageSize: 10,
        pageSizes: [10, 30, 50, 100, 200],
        // 用户总数
        total: 0,
        // 用户列表
        userList: [],
        uploadUsers: [],
        uploadUsersPage: [],
        uploadUsersCurrentPage: 1,
        uploadUsersPageSize: 15,
        // 搜索关键字
        keyword: '',
        // 是否显示用户对话框
        showUserDialog: false,
        // 当前用户model
        user: {},
        loadingTable: false,
        loadingGenerate: false,
        loadingChangeUserpassword: false,
        // 当前页码
        currentPage: 1,
        selectedUsers: [],
        syncingRouteState: false,
        formGenerateUser: {
          prefix: '',
          suffix: '',
          number_from: 0,
          number_to: 0,
          password_length: 8
        },
        formChangeUserpassword: {
          right_length: 0,
          suffix: '123456',
          match_type: 'type_schoolname'
        }
      }
    },
    mounted () {
      this.applyRouteState(this.$route)
      this.getUserList(this.currentPage, false)
    },
    methods: {
      applyRouteState (route) {
        const query = route.query || {}
        const parsedPage = parseInt(query.page)
        const parsedPageSize = parseInt(query.page_size)

        this.syncingRouteState = true
        this.keyword = query.keyword || ''
        this.currentPage = Number.isInteger(parsedPage) && parsedPage > 0 ? parsedPage : 1
        this.pageSize = this.pageSizes.includes(parsedPageSize) ? parsedPageSize : 10
        this.syncingRouteState = false
      },
      syncRouteQuery () {
        const query = {}
        if (this.keyword) {
          query.keyword = this.keyword
        }
        if (this.currentPage > 1) {
          query.page = String(this.currentPage)
        }
        if (this.pageSize !== 10) {
          query.page_size = String(this.pageSize)
        }

        const currentQuery = this.$route.query || {}
        const queryUnchanged = currentQuery.keyword === query.keyword &&
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
        this.getUserList(page)
      },
      handlePageSizeChange (pageSize) {
        this.pageSize = pageSize
        this.currentPage = 1
        this.getUserList(1)
      },
      // 提交修改用户的信息
      saveUser () {
        api.editUser(this.user).then(res => {
          // 更新列表
          this.getUserList(this.currentPage)
        }).then(() => {
          this.showUserDialog = false
        }).catch(() => {
        })
      },
      // 打开用户对话框
      openUserDialog (id) {
        this.showUserDialog = true
        api.getUser(id).then(res => {
          this.user = res.data.data
          this.user.password = ''
          this.user.real_tfa = this.user.two_factor_auth
        })
      },
      // 获取用户列表
      getUserList (page, syncRoute = true) {
        this.currentPage = page
        if (syncRoute) {
          this.syncRouteQuery()
        }
        this.loadingTable = true
        api.getUserList((page - 1) * this.pageSize, this.pageSize, this.keyword).then(res => {
          this.loadingTable = false
          this.total = res.data.data.total
          this.userList = res.data.data.results
        }, res => {
          this.loadingTable = false
        })
      },
      deleteUsers (ids) {
        this.$confirm('Sure to delete the user? The associated resources created by this user will be deleted as well, like problem, contest, announcement, etc.', 'confirm', {
          type: 'warning'
        }).then(() => {
          api.deleteUsers(ids.join(',')).then(res => {
            this.getUserList(this.currentPage)
          }).catch(() => {
            this.getUserList(this.currentPage)
          })
        }, () => {
        })
      },
      handleSelectionChange (val) {
        this.selectedUsers = val
      },
      generateUser () {
        this.$refs['formGenerateUser'].validate((valid) => {
          if (!valid) {
            this.$error('Please validate the error fields')
            return
          }
          this.loadingGenerate = true
          let data = Object.assign({}, this.formGenerateUser)
          api.generateUser(data).then(res => {
            this.loadingGenerate = false
            let url = '/admin/generate_user?file_id=' + res.data.data.file_id
            utils.downloadFile(url).then(() => {
              this.$alert('All users created successfully, the users sheets have downloaded to your disk.', 'Notice')
            })
            this.getUserList(1)
          }).catch(() => {
            this.loadingGenerate = false
          })
        })
      },
      changeUserpassword () {
        this.$refs['formChangeUserpassword'].validate((valid) => {
          if (!valid) {
            this.$error('Please validate the error fields')
            return
          }
          this.loadingChangeUserpassword = true
          let data = Object.assign({}, this.formChangeUserpassword)
          api.changeUserpassword(data).then(res => {
            this.loadingChangeUserpassword = false
            this.$alert('Great! Change user password success.', 'Notice')
          }).catch(() => {
            this.loadingChangeUserpassword = false
            this.$alert('Oh NO! Change user password fail...', 'Notice')
          })
        })
      },
      handleUsersCSV (file) {
        papa.parse(file, {
          complete: (results) => {
            let data = results.data.filter(user => {
              return user[0] && user[1] && user[2]
            })
            let delta = results.data.length - data.length
            if (delta > 0) {
              this.$warning(delta + ' users have been filtered due to empty value')
            }
            this.uploadUsersCurrentPage = 1
            this.uploadUsers = data
            this.uploadUsersPage = data.slice(0, this.uploadUsersPageSize)
          },
          error: (error) => {
            this.$error(error)
          }
        })
      },
      handleUsersUpload () {
        api.importUsers(this.uploadUsers).then(res => {
          this.getUserList(1)
          this.handleResetData()
        }).catch(() => {
        })
      },
      handleResetData () {
        this.uploadUsers = []
      }
    },
    computed: {
      selectedUserIDs () {
        let ids = []
        for (let user of this.selectedUsers) {
          ids.push(user.id)
        }
        return ids
      }
    },
    watch: {
      '$route' (newVal) {
        this.applyRouteState(newVal)
        this.getUserList(this.currentPage, false)
      },
      'keyword' () {
        if (this.syncingRouteState) {
          return
        }
        this.currentChange(1)
      },
      'user.admin_type' () {
        if (this.user.admin_type === 'Super Admin') {
          this.user.problem_permission = 'All'
        } else if (this.user.admin_type === 'Regular User') {
          this.user.problem_permission = 'None'
        }
      },
      'uploadUsersCurrentPage' (page) {
        this.uploadUsersPage = this.uploadUsers.slice((page - 1) * this.uploadUsersPageSize, page * this.uploadUsersPageSize)
      }
    }
  }
</script>

<style scoped lang="less">
  .import-user-icon {
    color: #555555;
    margin-left: 4px;
  }

  .userPreview {
    padding-left: 10px;
  }

  .notification {
    p {
      margin: 0;
      text-align: left;
    }
  }
</style>
