# 学习路径一期接口草案与验收

前端原型位于 `/user-home?tab=learning-path`，本人可见。真实后端尚未实现以下接口；Mock 使用同一请求结构。权限由后端基于会话校验，不接受任意 username 查询他人路径。

## 获取路径

`GET /api/learning-path`，可选 query：`path_id`、`revision`，用于恢复某一版本。统一响应 `{error: null, data: ...}`，HTTP/业务错误由 Tab 内展示。未登录返回 401。

`data.status`：`ready`、`generating`、`insufficient_data`、`empty`。非 ready 时带 `reason_code`、可展示的 `message`；generating 另带 `retry_after_seconds`（前端至少间隔 3 秒检查，离开 Tab 停止）。

ready 字段：

- `path_id: string`、`revision: number`：不可变内容版本。训练目标、题目和顺序改变必须生成新版本；旧版本返回最新判题进度。旧版本过期时需另行协商明确的恢复状态，不能悄悄替换。
- `generated_at`、`based_on_until`：ISO 时间，分别为生成时间与数据统计截止时间。
- `kind: personalized | starter`、`summary: string`。
- `focus_points: [{knowledge_id, label, assessment}]`；assessment 为 insufficient 时显示“待了解”，其他已有评估显示“建议巩固”。
- `evidence: [{text, sample_count, window_days}]`：规则程序给出的可核对依据，text 可直接显示；不足样本不作薄弱点判断。
- `steps: [{step_id, order, title, objective, status, reason_codes, explanation_available, problems}]`：按 order 排序返回，可包含多道题。status：pending、judging、completed。后端根据最终判题及业务规则判定完成。
- `problems: [{problem_id, display_id, title, context, availability, unavailable_reason, status}]`；problem_id 是稳定标识（当前 Mock 为数字），display_id 是页面路由题号；context 为 `{type: public}` 或 `{type: contest, contest_id}`。availability 为 available 才允许进入题目。
- `next_step_id`、`next_problem_id`：后端选定的可练习目标，无目标时为 null。
- `latest_path`：可选，新版完整路径，结构同 ready 数据，不递归包含 latest_path。前端显示提示，用户选择后替换。

字段集合允许增加，前端不生成题目和顺序，不依据点击行为更新完成状态。每次返回路径重新获取进度。`step` query 恢复展开位置，未知值回退当前建议。Tab 切换 replace query，题目跳转 push 历史记录；显式返回链接带上 path、revision、step。

## 推荐解释

`POST /api/learning-path/explanation`，body：`{path_id, revision, step_id}`。

后端根据会话、路径版本和步骤读取推荐依据，AI 只解释已存在的内容，不接受前端传入题单替换路径。

响应 data：`{path_id, revision, step_id, status: ready | unavailable, text, generated_at}`。版本/步骤不匹配返回 409。前端验证关联字段，以纯文本显示；第一次点击才请求，同一组件生命周期内缓存，同一步骤收起再展开不重复请求。失败可重试，练习按钮不受影响。

## Mock 预览

在 frontend 下运行 `PORT=8081 npm run dev:mock`，以实际输出端口为准。Mock 模式才显示场景选择器并传递 mock_path 字段，正式运行不传递。所有解释为固定模拟文案，不调用 AI。

场景：正常路径、入门路径、数据不足、暂无推荐、生成中、加载失败、解释失败、题目不可用、判题中、新版本提醒。生成中刻意保持该状态便于验收；更新按钮可检查当前状态。Mock 提交固定 AC，会更新路径进度，重启服务恢复初始数据。

验收重点：

1. 直接访问、刷新、Tab 切换，公共题库及参加的实验仍可用。
2. 默认展开当前建议；可查看其他步骤与分析依据。
3. 点击解释出现加载，再显示解释；重复展开复用；解释失败及重试不阻止开始练习。
4. 开始练习进入正确题目，显式返回与浏览器后退恢复步骤；Mock 提交后进度增加。
5. 非 ready 状态与网络失败分别反馈，更新失败保留已显示路径。
6. 新版本只提示，用户选择后才切换；版本对应解释缓存失效。
7. 非本人主页不提供路径；未知 tab 回退公共题库。
8. 沿用现有桌面布局。全站 body 现有 min-width: 900px，390px 检查确认仍需横向滚动；移动端导航与整体适配不在本次范围。

## 本次验证记录（2026-09-09）

- 独立 Mock 服务：127.0.0.1:8081，未操作原 8080 服务。
- Webpack 3 开发构建成功；修正 iView 2 初始化延迟隐藏 Tab 内容的问题（挂载前同步 Tab，关闭切换动画）。
- 浏览器验证：直接访问、刷新、原有两个 Tab 往返、题目返回链接、浏览器后退、未知 Tab 回退、他人主页重定向。
- 模拟提交 1002 后返回 step-2，进度由 1/3 变为 2/3，下一步变为 step-3。
- 已验证所有 10 个 Mock 场景，包括解释加载/失败/重试、首次加载失败及保留旧路径、新版本主动接受。
- 本次修改的 JS/Vue 文件 ESLint 通过，Mock 模块语法检查与 git diff --check 通过。全量 npm run lint 存在原有文件错误（ContestProblemList.vue、highlight 插件等），未将其计为通过。
- 尚未对接真实后端或调用 AI；未声称验证真实推荐质量、判题规则或后端权限实现。

## 简单兼容处理补充

- 前端用一个本地适配模块处理接口数据：path、revision、step 和 problem 标识接收字符串/数字，内部及后续请求统一为字符串。后端应接受这两种表示，不以 JSON 类型差异判断版本不一致。
- 缺失的展示文案、分析依据等提供默认值；重复标识、无效推荐引用显示 Tab 内的数据错误。未知题目 context 禁用入口，不猜测跳转位置。一步多题和实验题 context 保持支持。
- 未知练习状态显示“状态待确认”，未知知识点评估显示“评估待确认”；已掌握与已跳过有明确文案。
- path/revision query 变化重新请求，step 变化只改变展开位置。接受新版本立即使旧请求失效，响应还需匹配请求版本。旧解释也不会进入新路径。
- 401/not_authenticated 打开登录入口；409、410、version_mismatch、version_expired 提供“查看最新路径”（清除旧版参数再请求）；403 显示无权限；429/503 显示服务繁忙；网络与无效数据分别反馈。200 业务错误仍保留错误码，不改动其他功能的请求封装。
- 新增 Mock 场景：扩展字段与多题、无效推荐引用、旧版本失效、登录过期。旧版本失效需要 URL 含 revision 才触发，清除参数后恢复正常路径；登录过期只模拟该接口的 401，不退出共享模拟账号。
- 回归命令（frontend 目录）：`node build/test-learning-path.js`。覆盖实际 Vue 响应式路由监听、迟到请求、版本关联、旧解释、数据校验、错误分类及回调式 Router 导航；未引入新测试依赖。
