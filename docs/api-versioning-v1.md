# XMUOJ-AI API 版本、认证与响应规范

- 版本：1.0.0
- 状态：已批准／冻结
- 更新日期：2026-08-10

## 统一规则

- OpenAPI `info.version`、Schema `schema_version` 和文档契约版本均使用 SemVer。
- 已发布的端点路径在 1.x 中保持稳定；对现有客户端不兼容时使用新主版本路径或并行部署。
- 每个响应均返回 `X-API-Version: 1.0.0`。
- 成功和失败都使用 `{error, data, request_id}` 包装；`request_id` 在单次请求中唯一并进入服务端日志。
- HTTP 状态表达传输/资源结果，`error` 表达稳定业务码；不再用 HTTP 200 包装所有失败。

## 认证与 CSRF

- 第一期使用现有 Django Session Cookie，用户 ID 只来自认证上下文。
- `POST`、`PUT`、`PATCH`、`DELETE` 等写请求必须校验 CSRF，OpenAPI 用 `X-CSRFToken` 显式声明；新增 API 不得继承 `CSRFExemptAPIView`。
- 未认证返回 401；已认证但无功能权限返回 403；对象不存在或不在当前用户数据范围内统一返回 404，不泄露对象存在性。

## 兼容性

1.x 可新增可选响应字段或新端点；不得删除字段、改变已有字段语义、将可选改为必填、收紧枚举或改变默认分页顺序。这些变更必须升级主版本。
