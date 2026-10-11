# XMUOJ-AI 前端代码导览

本文记录当前 Vue 3 前端入口与维护边界。启动命令见 [README](README.md)，全仓库说明见[根 README](../README.md)。

## 技术与目录

学生端使用 View UI Plus，管理端使用 Element Plus；共同使用 Vue 3 Options API、Vue Router 4、Vuex 4 和 Vue I18n 11。Vite 负责两个入口的开发服务与生产构建，具体依赖版本以 package.json 和 package-lock.json 为准。

| 位置 | 职责 |
| --- | --- |
| index.html、admin/index.html | 学生端和管理端 HTML 入口 |
| src/pages/oj/ | 学生页面、路由、API 及页面组件 |
| src/pages/admin/ | 管理页面、路由、API 及页面组件 |
| src/store/ | 用户、比赛及全局状态 |
| src/i18n/ | 中文、英文、繁体中文文案及组件语言包 |
| src/components/、src/services/ | 共享 Vue 3 组件、消息服务、路由状态同步、监控接入 |
| src/plugins/、src/utils/ | 高亮、数学公式、复制、时间和存储等工具 |
| src/styles/、src/assets/legacy-icons/ | 学生端旧外观兼容主题及保留的图标资源 |
| build/mock-*.js | Mock API、页面数据及 AI 场景 |
| tests/、vitest.config.mjs | Vue Test Utils 2、jsdom 与 Vitest 回归测试 |
| vite.config.mjs、build/dev-server.mjs | 构建、多入口回退、代理、Mock 服务与开发启动 |
| vendor/ | Simditor 所需的三个固定历史依赖及许可证 |
| static/、deploy/ | 静态资源与部署配置 |

## 页面与数据流

学生入口由 src/pages/oj/index.js 创建 Vue 应用，路由位于同目录 router/；管理入口位于 src/pages/admin/index.js，路由位于 router.js。普通页面通过各自 api.js 请求后端，Vuex 保存共享状态。保持现有 URL、查询参数、权限判断和 API 请求格式。

| 模块 | 主要页面与维护重点 |
| --- | --- |
| 题库与做题 | ProblemList.vue、Problem.vue；筛选、分页、编辑器、提交与轮询 |
| 比赛 | ContestDetail.vue 及 children/；题目、ACM/OI 榜单、权限与倒计时 |
| 提交 | SubmissionList.vue、SubmissionDetails.vue；筛选、结果、代码与高亮 |
| 个人主页与设置 | UserHome.vue、setting/；主页 Tab、资料、头像、账号与会话 |
| 管理端 | problem/、contest/、general/；表单、表格、批量操作、上传与弹窗 |

四项 AI 原型分别是个人主页的学习路径与学习反馈、题目页的解题引导、提交详情的代码解读。独立的数据适配、API helper 和 Mock 文件与页面按功能组织；真实 AI 后端不由 Mock 实现。生成操作由用户主动触发，路由、账号或题目变化时必须继续隔离迟到响应。详细契约见 [AI 功能原型说明](docs/ai-feature-prototypes.md)。

## Vue 3 维护约定

- 应用入口使用 createApp；全局消息、HTTP 和格式化函数由应用注册。模板通过 $filters 调用格式化函数，不使用 Vue 2 filter 语法。
- 组件使用命名 slot、具名 v-model、emits 和 beforeUnmount；路由过渡通过 RouterView slot 取出页面组件。
- 表格 render 回调使用 Vue 3 VNode 属性和组件解析，事件为 onClick 等属性。修改列时同时检查点击、颜色、宽度和滚动。
- CodeMirrorInput.vue 保留 CodeMirror 5 引擎；Chart.vue 保留 ECharts 3 引擎。避免在一般页面维护中顺带更换编辑器或图表引擎。
- 学生端 LegacyButton、LegacyIcon 与 legacy-theme.less 负责旧外观；管理端在 Element Plus 上保留旧尺寸和图标。变更组件库或样式后需重新检查两端布局。
- Simditor 继续使用原编辑器核心；头像使用 Vue 3 版本 VueCropper。组件卸载时释放编辑器、图表及计时器。

## 开发、测试与产物

使用 Node.js 24 和 npm 11+，在 frontend/ 执行：

| 命令 | 用途 |
| --- | --- |
| npm ci | 安装锁定依赖 |
| npm run dev | 启动真实后端代理模式 |
| npm run dev:mock | 启动本地 Mock 模式 |
| npm run lint | 检查源码、构建脚本和测试 |
| npm test | 运行回归测试 |
| npm run build | 构建生产静态产物 |
| npm run preview | 本地预览生产产物 |

TARGET 控制开发代理目标，PORT 控制本地端口。生产构建始终关闭 Mock。Vite 输出 dist/index.html、dist/admin/index.html 和 dist/static/；部署端需正确处理学生和管理路由的 HTML 回退，同时保留 /api 与 /public 服务。

浏览器范围为 Chrome、Edge、Firefox 最近两个版本及 Safari 16.4+。不再支持 IE，也不再使用 Webpack DLL、旧 config/ 环境文件或 vue-codemirror-lite/vue-echarts 的 Vue 2 封装。旧构建配置已删除，历史版本可通过 Git 查阅。

测试应覆盖路由直达与刷新、表单校验、分页、代码编辑与提交、榜单、管理端操作和 AI 请求隔离，详见 [Vue 3 测试矩阵](docs/vue3-test-matrix.md)。npm run build 不部署；build.sh 与 redeploy_local.sh 是显式容器部署入口，运行前核对目标环境。

## 历史记录：与上游 OnlineJudge 后端的关系

> 以下保留原上游说明，仅供历史参考。仓库地址、API 示例、认证方式、数据库、框架版本和部署关系不代表当前 XMUOJ-AI；当前后端以根 README、backend/ 源码和实际接口为准。

### 15.1 OnlineJudge 项目概述

OnlineJudge 是一个完整的在线判题系统，由多个模块组成：

- **后端(Django)**：[https://github.com/shaohuihuang/OnlineJudge](https://github.com/shaohuihuang/OnlineJudge)
- **前端(Vue)**：[https://github.com/shaohuihuang/OnlineJudgeFE](https://github.com/shaohuihuang/OnlineJudgeFE)
- **判题沙箱(Seccomp)**：[https://github.com/shaohuihuang/Judger](https://github.com/shaohuihuang/Judger)
- **判题服务器**：[https://github.com/shaohuihuang/JudgeServer](https://github.com/shaohuihuang/JudgeServer)

### 15.2 OnlineJudge 后端架构

OnlineJudge 后端是基于 Django 和 Django Rest Framework 开发的 API 服务，主要包含以下模块：

| 模块 | 职责 |
|-----|------|
| `account` | 用户账户管理，包括注册、登录、个人资料等 |
| `announcement` | 公告管理，发布系统公告 |
| `conf` | 系统配置，包括网站设置、评测服务器管理 |
| `contest` | 比赛管理，支持 ACM/OI 两种比赛模式 |
| `judge` | 判题相关，处理代码评测逻辑 |
| `problem` | 题目管理，包括题目创建、编辑、测试用例管理 |
| `submission` | 提交管理，处理用户代码提交和评测结果 |
| `utils` | 工具函数，提供通用功能支持 |

### 15.3 前后端交互关系

OnlineJudgeFE 作为前端项目，通过 API 调用与 OnlineJudge 后端进行交互：

1. **API 调用**：前端通过 Axios 发送 HTTP 请求到后端 API 端点
2. **数据传输**：后端返回 JSON 格式的数据，前端解析并展示
3. **认证机制**：使用 JWT 或 Session 进行用户认证
4. **实时更新**：对于比赛排名等需要实时更新的功能，前端通过定时轮询获取最新数据

### 15.4 核心 API 接口

| API 端点 | 功能描述 | 前端调用 |
|---------|---------|----------|
| `/api/auth/login/` | 用户登录 | `login` 函数 |
| `/api/auth/register/` | 用户注册 | `register` 函数 |
| `/api/problems/` | 获取题目列表 | `getProblemList` 函数 |
| `/api/problems/{id}/` | 获取题目详情 | `getProblem` 函数 |
| `/api/submissions/` | 提交代码 | `submitCode` 函数 |
| `/api/submissions/{id}/` | 获取提交详情 | `getSubmission` 函数 |
| `/api/contests/` | 获取比赛列表 | `getContestList` 函数 |
| `/api/contests/{id}/` | 获取比赛详情 | `getContest` 函数 |
| `/api/contests/{id}/rank/` | 获取比赛排名 | `getContestRank` 函数 |

### 15.5 部署关系

两个项目的部署关系如下：

1. **后端部署**：OnlineJudge 后端部署为 Django 应用，提供 API 服务
2. **前端部署**：OnlineJudgeFE 构建后部署为静态文件，通过 Nginx 或其他 Web 服务器提供访问
3. **反向代理**：通过 Nginx 配置反向代理，将前端的 API 请求转发到后端服务
4. **判题服务**：JudgeServer 和 Judger 部署为独立服务，与后端通过网络通信

### 15.6 技术栈对比

| 类别 | OnlineJudge (后端) | OnlineJudgeFE (前端) |
|-----|-------------------|---------------------|
| 语言 | Python 3.8.0+ | JavaScript |
| 框架 | Django 3.2.9, Django Rest Framework 3.12.0 | Vue 2.5.13, Vuex 3.0.1, Vue Router 3.0.1 |
| 数据库 | MySQL | - |
| 缓存 | Redis | - |
| UI 组件 | - | iView 2.13.0, Element UI 2.3.7 |
| 数据可视化 | - | ECharts 3.8.5 |
| 构建工具 | - | Webpack 3.6.0 |

### 15.7 项目协作流程

1. **后端开发**：实现 API 接口和业务逻辑
2. **前端开发**：根据 API 文档实现用户界面和交互
3. **联调测试**：前后端联调，确保 API 调用正常
4. **部署上线**：同时部署后端和前端服务

通过这种前后端分离的架构，使得项目具有更好的可维护性和扩展性，同时也便于团队协作开发。
