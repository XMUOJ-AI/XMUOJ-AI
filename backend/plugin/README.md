# 插件登录与会话

插件复用网页端的 Django Session。客户端必须按站点维护 Cookie jar，接收并保存服务端的 `Set-Cookie`，在后续请求中发送对应 Cookie；生产环境使用 HTTPS，遵守 Cookie 的 Secure、Path 和过期属性。

1. 请求 `GET /api/plugin/bootstrap`。未登录时 `data.user` 为 `null`；响应包含 `data.csrf_token` 并设置 CSRF Cookie。已存在有效网页 Session 时，此接口直接返回当前用户。
2. 请求 `POST /api/plugin/login`，JSON 包含 `username`、`password`，开启双因素认证时还需 `tfa_code`。同时发送步骤 1 的 Cookie 和 `X-CSRFToken: <data.csrf_token>`。缺少有效 CSRF 校验返回 HTTP 403。
3. 登录成功仍返回 `data.token` 和 `data.user`，并增加 `data.csrf_token`。保存新 Session/CSRF Cookie，并用这次返回的新 `csrf_token` 替换登录前的值。Django 登录会轮换匿名 Session 标识和 CSRF 凭据；切换账号会使原 Session 失效，同账号重新登录继续使用当前 Session。
4. 查询继续携带 Cookie。提交代码等 POST/PUT/PATCH/DELETE 请求还须携带当前 `X-CSRFToken`。例如 `POST /api/plugin/submission` 的 JSON 为 `{"problem_id": 123, "language": "C", "code": "..."}`。HTTPS 写请求同时发送同站点 HTTPS `Referer`，满足 Django 的来源校验；该规则也适用于登录和退出。
5. 退出使用 `POST /api/plugin/logout`，同样携带 Cookie 和 CSRF header。成功后当前 Session 被注销，并清空账号原有的 SSO token；同账号其他独立 Session 保持有效。再次登录先请求 bootstrap。

`data.token` 为兼容保留的 SSO 身份查询凭据，继续供既有 `/api/sso` 使用；它不用于插件请求鉴权，`Authorization: Bearer <token>` 不会建立插件身份。客户端迁移时必须采用上述 Cookie + CSRF 流程，不能仅保存旧 token。原有 APPKEY/OpenAPI 机制保持既有用途，本次未扩展。

凭据错误、双因素验证未完成或账号已停用时，不建立新登录会话。登录失败保留原有有效会话；账号被停用后，其既有 Session 会在后续请求中失效。会话过期或被撤销后，通过 bootstrap 的 `data.user` 判断是否需要重新登录。

回归入口：在 `backend/` 目录运行 `python manage.py test plugin.test_auth --settings=oj.settings`。测试使用实际 Session、CSRF 中间件和数据库，覆盖登录后的查询与提交入库；异步判题由现有 outbox 记录，测试不调用外部 Judge。
