# Vue 3 迁移验收矩阵

固定 Mock 数据仅用于本地预览，不调用真实判题、邮件、上传存储或数据库。`npm run dev:mock` 默认登录 `mock_student`；登录用户名 `mock_admin` 切换超管，`mock_other` 切换另一学生。开发工具可向 `/api/__mock/session` POST `{ "role": "student|other|admin|guest" }`，再刷新页面或重新拉取 profile。该接口只由开发 Mock 挂载。

| 页面/场景 | 固定入口 | 核对点 |
| --- | --- | --- |
| 首页/题库 | `/`、`/problem` | 导航、公告、搜索、筛选、分页、表格点击 |
| 编辑器/公开下载 | `/problem/1001` | 输入、语言/主题切换、文件导入、模拟提交、样例复制、下载响应 |
| 受限下载/引导 | `/problem/1002?mock_guidance=available` | 隐藏受限下载；三阶段、等待/限额、失败重试 |
| 提交分析 | `/status/mock-ac/`、`/status/mock-wa/` | 原代码/判题、折叠缓存、主动生成、切提交隔离 |
| 个人主页 | `/user-home?tab=contests`、`tab=learning-path`、`tab=learning-feedback` | Tab/路由恢复、实验详情、路径解释、资料引用、账号切换 |
| ACM 实验 | `/contest/1/problems`、`/contest/1/rank`、`/contest/1/submissions` | 题目、排名表格与图表、菜单权限 |
| OI 已结束实验 | `/contest/2/problems`、`/contest/2/rank` | 得分列、条形图、结束后禁交 |
| 私有/未开始 | `/contest/3/`、`/contest/4/` | 口令 `mock123`、错误口令、不同账号不共享授权、未开始限制 |
| 全站排名/设置 | `/acm-rank`、`/oi-rank`、`/setting/profile`、`/setting/account`、`/setting/security` | 图表、裁剪/头像、表单验证、会话 |
| 后台首页 | `/admin/`（先登录 mock_admin） | 指标、当前会话、布局、菜单权限 |
| 后台列表 | `/admin/user`、`/admin/problems`、`/admin/contest`、`/admin/announcement` | 搜索、分页、选择、弹窗、编辑保存 |
| 后台编辑/标签 | `/admin/problem/edit/1`、`/admin/problem/create`、`/admin/problem/tags`、`/admin/contest/1/edit` | 富文本、样例、上传、语言、日期、标签增改删 |
| 后台其他 | `/admin/conf`、`/admin/judge-server`、`/admin/prune-test-case`、`/admin/problem/batch_ops` | 配置、开关、导入导出、上传下载权限 |

桌面对照视口为 1440×900。响应式断点检查宽度为 390、767、768、769、991、992、993、1199、1200、1201、1440；使用同一浏览器、语言、字体及固定数据，并等待字体、动画和异步内容稳定。初始提交、反馈依据窗口及模拟解释的展示基准时间为 2026-09-19 14:00（+08:00）；用户新建提交保留操作时间，可能推进反馈窗口。引导冷却、生成延迟和超时仍用真实计时。

截图仅证明所捕获的视口或裁切区域，不覆盖未显示的下半页、隐藏弹窗或所有页面×状态×断点组合；本矩阵是检查清单，不代表每格都有完整截图。动态计时和用户操作后的数据不作逐像素一致承诺。开发修改保存在当前进程内，重启恢复。

自动回归保留第一期五组全部关键边界：数据形状、未知状态、来源缺失、身份/路径/判题版本与竞态、按需生成、请求幂等、Mock 能力/权限、生产参数隔离、代码行号重复及旧代码清空。组件回归由 Vue Test Utils 2 在真实 Vue 3 响应式与生命周期下执行，Mock HTTP 回归验证学生/超管/游客的读写和上传下载权限。

在 `frontend/` 执行 `npm test` 运行全部 Vitest 测试；也可以沿用 `node build/test-learning-path.js` 等五个历史命令，它们转发到相应的新测试。Mock HTTP 用例会临时监听 127.0.0.1 随机端口并在结束后关闭。

## 自动化验收记录（2026-09-19）

- 干净目录排除原有 `node_modules` 和 `dist`，使用 Node **24.19.0**、npm **12.0.2** 执行 `npm ci --include=dev` 成功。锁文件在无已有依赖的目录重新生成并回写；运行时依赖版本及 vendored 源码未调整。
- 全仓 `npm run lint` 通过；`npm test` **14 组、49 条**全部通过。新增覆盖真实 KaTeX/代码高亮引擎的 DOM 更新、设置页资料晚到与保存竞态、OI 排名权限及迟到响应、真实 Element Plus 标签开关，以及编辑器和公共组件绑定。
- `npm ls vue @vue/compat vue-template-compiler --all` 仅出现 Vue **3.5.43**，没有 Vue 2、兼容运行时或旧模板编译器。
- 无 Git 元数据且不设置 `VERSION` 的源码副本可生产构建，版本采用 `source` 回退。普通构建及 CDN 前缀构建都保留 `dist/index.html`、`dist/admin/index.html`、`dist/static`；86 个引用资源/字体均存在，没有旧 DLL 或 Mock fixture 标记。
- 构建时同时设置 `MOCK`、`MOCK_PREVIEW`、`AI_FEATURES_MOCK`、`LEARNING_PATH_MOCK` 仍关闭生产 Mock。真实 Vite HTTP 验证覆盖 Mock JSON/权限响应、OJ/admin 深链接，以及真实代理的路径、会话 cookie 和 `TARGET` Referer。
- 已构建产物的四个深链接 `/problem/1002`、`/user-home?tab=learning-feedback`、`/admin`、`/admin/problem/edit/1` 返回 200 并载入正确入口；CDN 检查验证生成 URL 前缀，不代表对外部 CDN 服务进行上线验收。

构建后可执行 `node tests/verify-production.mjs` 复查入口、资源和 Mock 隔离。此次日志保存在 `/private/tmp/xmuoj-vue3-final-check-logs/`，包括环境、安装结果、依赖树、lint、test、普通/CDN 构建、资源与深链接结果。

残余构建警告为部分 chunk 大于 500 kB。安装仍报告旧编辑器等依赖的弃用、engine 和审计提示；本次未做破坏性自动升级，不将前端迁移验收等同于依赖安全审计清零。

真实后端、RAG/LLM质量以及真实文件存储不属于这份 Mock 的验收能力。后台批量操作使用固定成功响应，用于表单和交互验证；复杂治理算法仍由后端测试负责。生产构建另查双入口深链接、`/static`资源、CDN前缀及关闭Mock。
