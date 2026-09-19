# 第一期 AI 前端原型

当前包含学习路径、学习反馈、解题引导和提交代码解读。后三项为前端与固定 Mock；真实后端、检索、LLM 和教学权限策略尚未实现。

在 `frontend/` 运行 `npm run dev:mock`，默认端口 8080。需要更换端口时使用 `PORT=8090 npm run dev:mock`。Mock 数据保存在进程内，重启服务恢复初始状态，不连接真实后端。

| 功能 | 预览入口 | 交互重点 |
| --- | --- | --- |
| 学习路径 | `/user-home?tab=learning-path` | 目标、推荐原因、练习与返回；保留原有实现 |
| 学习反馈 | `/user-home?tab=learning-feedback` | 主动生成近期回顾、复习建议，展开资料摘录 |
| 解题引导 | `/problem/1002?mock_guidance=available` | 先描述理解，再按三个阶段获得追问；默认入口需等待 30 秒 |
| 代码解读 | `/status/mock-ac/`、`/status/mock-wa/` | 默认折叠，点击生成；原判题结果与代码保持可用 |

## 异常场景

- 学习反馈：页面内选择 Mock 场景；覆盖无记录、依据不足、失败重试、登录过期、引用不可用等。
- 解题引导：`mock_guidance=waiting|insufficient|failure|pending|exhausted|disabled|unknown|permission-error`。刷新保留等待时间与额度；比赛必须获得显式能力授权。
- 代码解读：记录 `mock-tle`、`mock-re`、`mock-ce`、`mock-pending`、`mock-other`；`mock_analysis=truncated|busy|quota|expired|failed|insufficient|mismatch|version|slow`。普通模拟提交没有固定分析素材，会显示依据不足。

## 后端接入边界

三个独立 `*Api.js` 和 `*Data.js` 模块定义拟定请求与响应，需和后端确认后接入：

| 功能 | `/api` 下的接口 |
| --- | --- |
| 学习反馈 | `GET /learning-feedback`、`POST /learning-feedback/generations`、`GET /learning-feedback/generations/:id` |
| 解题引导 | `GET /problem-guidance`、`POST /problem-guidance/messages` |
| 代码解读 | `GET /submission-analysis`、`POST /submission-analysis/generate` |

服务端负责身份、访问权限、比赛策略、额度与版本判断。前端验证响应关联并隔离旧请求，不能替代后端授权。生成仅由用户操作触发；解题引导重试复用请求 ID。生产构建关闭所有 Mock 控件与请求参数。

## 回归检查

在 `frontend/` 分别运行 `node build/test-learning-path.js`、`node build/test-learning-feedback.js`、`node build/test-problem-guidance.js`、`node build/test-submission-analysis.js`。覆盖数据形状、身份／版本关联、旧请求隔离、主动生成及关键 Mock 状态。

`node build/test-code-highlight.js` 检查提交代码切换后的行号重复与旧代码残留问题。

## 本阶段验收（2026-09-19）

验收范围为四个入口的可交互原型、Mock、拟定数据边界、异常状态及 Vue 2 兼容性。真实接口联调、后端授权和模型效果单独验收。

- 学习路径：路径、依据与按需解释、练习跳转和返回恢复；账号变化隔离旧请求，清空前一账号的路径及参数。
- 学习反馈：主动生成、近期记录、知识点建议和引用展开；加载、失败、禁用、依据不足和身份变化降级。
- 解题引导：三阶段追问、等待与额度、失败重试；响应丢失后查询失败仍保留原请求 ID，确认已处理后清空旧输入，生成中也保留待确认请求。
- 代码解读：本人提交、AC/WA/TLE/RE、CE/等待、分析范围、权限和判题版本隔离；原代码与判题结果仍可查看。

两项复核问题均先由新增测试复现，再验证修复。五组回归测试、此次改动文件 lint 与生产构建通过；浏览器复验路径返回参数、按需解释与引导失败重试。全仓既有 lint 问题不计为通过，前端原型完成不代表一期其他分工已验收。
