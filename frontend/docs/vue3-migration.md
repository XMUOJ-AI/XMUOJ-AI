# Vue 3 迁移记录

基线：`fuyue/tab` 的 `a817bbd6fb24cad326234d39730ca03dc5dc296e`。实施分支：`fuyue/vue3-migration`。本次覆盖学生端、管理端、四个 AI 前端功能与本地 Mock；没有部署生产或修改 AI 后端。

## 实现

| 部分 | 当前实现 |
| --- | --- |
| 框架 | Vue 3.5.43、JavaScript、Options API；不使用 Vue 2 或 `@vue/compat` |
| 构建 | Vite 8.3.0 双 HTML 入口；移除 Webpack、Babel 6、DLL、OpenSSL 旧参数和 yarn 锁文件 |
| 路由 / 状态 | Vue Router 4.6.4、Vuex 4.1.0；保留路由、query、存储键及权限规则 |
| 国际化 | vue-i18n 11.4.12；三种语言及原文案；Moment 共用一个实例加载中文时间语言包 |
| UI | View UI Plus 1.3.24 / Element Plus 2.14.6；恢复旧字号、配色、间距、断点及图标字体 |
| 编辑器 / 图表 | 保留 CodeMirror 5、Simditor、ECharts 3 核心；Vue 3 封装负责同步、光标、滚动和销毁 |
| 辅助能力 | Vue 3 裁剪器、复制/高亮/公式指令；公式只操作自有内容叶子，避免破坏 Vue 的片段节点 |
| 工具链 | Node 24，统一 `package-lock.json`，`npm ci --include=dev`，Vitest / VTU 2 / jsdom |

Simditor 的三个 Git 来源依赖以原版本 MIT 源码保存在 `vendor/`，保留许可证。干净锁文件不再包含旧 Git 解析项或悬空链接。旧图标字体、按钮/主题规则的许可证保存在 `src/assets/legacy-icons/`。

原部署产物仍为 `dist/index.html`、`dist/admin/index.html` 和 `dist/static/**`。`STATIC_CDN_HOST` 控制构建资源前缀；`TARGET`、`PORT`、CSRF、代理 Referer 与 API 响应结构保持原约定。没有 Git 元数据的源代码副本也可构建；可显式传 `VERSION`。

`dev:mock` 只监听 `127.0.0.1`，不代理真实后端。所有生产构建模式都把两个 AI Mock 编译开关设为 `false`，不受 `MOCK` 等环境变量影响。生产预览的 `MOCK_PREVIEW=1` 只为接口提供测试数据，不启用生产包内的 AI Mock 功能。

## 回归中修复的问题

- Router 4 取消导航后不能把目标比赛同步到 Vuex；学习路径导航使用 Router 4 Promise。
- 异步资料到达前，设置表单可能已挂载；现在同步未编辑字段，并隔离切账号、卸载和已排队的旧保存响应。
- 公式渲染不能替换 Vue 管理的片段锚点；题面所有富文本叶子仍支持公式，纯文本来源保持转义。
- 空代码不交给旧行号插件处理；重复更新不会嵌套行号，空值会清掉上一份代码。
- 隐藏的 OI 排名不操作图表引用；权限晚到后初始化，失权或切比赛后忽略旧响应。
- ECharts 更新恢复旧 `notMerge` 行为；CodeMirror 外部更新保留光标/滚动并抑制事件回传。
- 后台标签开关使用 Element Plus 的 `model-value`；SPJ 确认取消不会改变复选框状态。
- Mock 补齐比赛公告、榜单、语言配置、验证码占位图、头像、二维码占位图及上传下载契约。

## 已执行的浏览器验收

学生端 32 个固定路由/状态完成最终加载检查，未发现新增 Vue 警告或运行错误；另验证管理员 OI 榜单及 ACM 辅助页。后台 18 个内容路由及登录页见 [管理端记录](./vue3-admin-acceptance.md)。

实际操作覆盖：学习路径解释与开始练习、解题引导提交/扣次、提交解读生成、学习反馈与引用展开；代码文件导入、语言/主题切换、样例复制、提交与判题轮询；头像选择/旋转/裁剪/Mock 上传；三语言保存；私有实验错误/正确口令；后台登录校验、公告和代码模板保存、SPJ 确认、标签启停/批量弹窗及测试用例上传。

同一浏览器、简体中文、1440×900 下对照了主要卡片、表格、表单、编辑器和图表的 DOM 尺寸。学习路径在 390、767、768、769、991、992、993、1199、1200、1201、1440px 下的容器、侧栏、Tab、路径和步骤尺寸逐项一致。每个断点使用同一个浏览器标签往返旧版/新版，并读取实际 `innerWidth`，避免仅调整一个标签造成错误对照。后台相同 11 个宽度的结果已单独记录。

可复现的固定场景与测试入口见 [验收矩阵](./vue3-test-matrix.md)。

## 自动与构建验收结果

2026-09-19，Node **24.19.0**、npm **12.0.2**：

| 检查 | 结果 |
| --- | --- |
| 无 `node_modules` 的源码副本 `npm ci --include=dev` | 通过；主工作目录也完成一次独立干净安装 |
| `npm run lint` | 通过 |
| `npm test` | 14 组、49 项通过；含原五组业务断言及真实组件/指令回归 |
| 依赖树 | 仅 Vue 3.5.43，无 Vue 2 或兼容构建 |
| 不含 Git 元数据且未设置 `VERSION` 的生产构建 | 通过 |
| 普通 / CDN 构建 | 均通过；两个 HTML 入口、86 项资源/字体引用有效 |
| 真实 Vite Mock / TARGET 代理 | API、HTML 路由回退、Cookie 与 Referer 契约通过 |
| 生产预览深链接 | 两端四条入口/深链接通过 |
| 生产 Mock 隔离 | 同时开启所有 Mock 环境变量仍关闭两个编译开关，产物无 fixture 标记 |

主目录普通生产产物另经真实浏览器验证：学生题目深链接正常，代码编辑器和旧图标加载正常，AI 区域不显示 Mock 控件；管理端登录后直接刷新题目编辑深链接，4 个富文本编辑器与 2 个代码编辑器正常加载，无新增运行错误或警告。

构建仅保留大于 500 kB 的分包体积提示，没有未解析的导入或资源。详细命令日志保存在本次机器的 `/private/tmp/xmuoj-vue3-final-check-logs/`，不作为需要安装或部署的项目文件。

## 验收边界与合并门槛

- 当前浏览器工具在 1440×900 覆盖下仍会裁切截图，全页截图有拼接异常。已经完成可见截图抽查和 DOM 尺寸对照，**尚未完成原计划要求的全部路由/状态完整截图及像素差分交付**。
- 浏览器操作使用内置 Chromium，不等同于逐一运行 Chrome、Edge、Firefox 和 Safari 的完整矩阵。
- Blob 下载按钮已检查触发及错误状态，HTTP 测试检查响应/权限；工具未提供可靠下载事件，因此没有声称已验证文件落盘。
- 上传、保存、判题仅验证 Mock 闭环。真实存储、判题服务和 AI 质量仍属后续联调。
- 保留的旧编辑器/图表等依赖仍有 npm 审计提示；本次没有执行会改变业务表现的强制依赖升级。

按“所有迁移检查通过后合入”的约定，视觉门槛未完全满足前保留独立迁移分支，不把抽查结果改写为全量通过，也不自动合入 `fuyue/tab`。

## 本地使用与回退

在 `frontend/` 下运行：

```sh
nvm use
npm ci --include=dev
npm run dev:mock
# 实际后端：TARGET=http://127.0.0.1:8000 npm run dev
npm run lint
npm test
npm run build
```

Mock 默认账号为 `mock_student`；登录 `mock_admin` 可查看后台。同一端口的 Mock 标签共享模拟身份，多角色并行验证应使用不同端口。`PORT=8095 npm run dev:mock` 可指定端口。

旧版基线提交 `a817bbd` 保留不变。在独立工作目录检出该提交、按该版本 README 安装依赖和启动，即可恢复旧版对照。不要用 Vue 3 的 `node_modules` 运行旧版，也不要用旧版依赖运行迁移分支。

迁移接口依据：[Vue 迁移指南](https://v3-migration.vuejs.org/migration-build.html)、[Router 4 迁移指南](https://router.vuejs.org/guide/migration/)、[Element Plus 迁移指南](https://element-plus.org/en-US/guide/migration)。
