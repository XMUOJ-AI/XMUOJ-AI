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
