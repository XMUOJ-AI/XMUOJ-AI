# HTTPS 部署配置

本轮实现的目标是生产浏览器入口全站 HTTPS。仓库配置不能证明实际生产域名、证书或网关已配置；上线前必须在真实入口复验。本地开发默认 HTTP；`OJ_ENV=production` 默认直接 TLS 模式，安全 Session/CSRF Cookie 与 1 小时 HSTS 开启。

| 环境变量 | 值及用途 |
| --- | --- |
| `OJ_HTTPS_MODE` | `direct`：本容器 Nginx 终止 TLS；`proxy`：受信任网关终止 TLS；`off`：仅显式选择的隔离 HTTP 测试环境 |
| `OJ_TRUSTED_PROXY_CIDRS` | proxy 模式必填，逗号分隔的代理源 IP/CIDR，例如 `192.0.2.10/32`；必须换成实际值，拒绝 `0.0.0.0/0` 和 `::/0` |
| `OJ_HSTS_SECONDS` | 默认 `3600`，允许 `0` 至 `31536000`；确认域名持续可用 HTTPS 后再延长 |
| `FORCE_HTTPS` | 旧配置兼容；显式 `OJ_HTTPS_MODE` 优先 |

## 直接 TLS

将正式证书和私钥配置到 `/data/ssl/server.crt`、`/data/ssl/server.key`，在网关或端口映射上把公网 443 接到容器 1443、80 接到 8000。没有证书时启动脚本生成的自签证书只供本地隔离验收，不构成生产 TLS 验收。重定向使用标准 HTTPS 域名端口；若本地映射为 18443，应直接使用该 HTTPS 地址测试，不把标准 443 重定向当作本机高端口地址。

Nginx 使用真实连接协议覆盖 `X-Forwarded-Proto`；外部客户端伪造该头不能关闭 HTTP 跳转。Session 和 CSRF Cookie 带 `Secure`；HSTS 同时覆盖 HTML、静态资源及 API。子域覆盖和 preload 保持关闭。

## 网关 TLS

配置 `OJ_HTTPS_MODE=proxy` 和精确的 `OJ_TRUSTED_PROXY_CIDRS`。网关必须删除用户提交的 `X-Forwarded-Proto`/`X-Forwarded-For`，写入自己的协议值及真实客户端地址；后端端口应只向这些网关及内部服务开放。Nginx 只接受这些源地址发来的小写值 `https`，其他来源按照真实连接协议处理并跳转。

同一组可信 CIDR 也用于 Nginx realip 模块，恢复实际客户端 IP，再由 Nginx 写入 `X-Real-IP`，供会话记录与比赛 IP 白名单使用。协议头是否可信始终按原始 TCP 对端 `$realip_remote_addr` 判断，不能把恢复后的学生 IP 当作网关地址。旧的任意 `LOWER_IP_HEADER` 替换逻辑已移除；多级代理必须逐级清洗请求头并明确可信链路。[Nginx realip 文档](https://nginx.org/en/docs/http/ngx_http_realip_module.html)

Django 的 `SECURE_PROXY_SSL_HEADER` 仅信任本容器 Nginx 已校验和覆盖的头。Gunicorn 始终绑定 `127.0.0.1:8080`，不得改为直接对外开放；否则该信任边界不再成立。HTTPS 跳转由 Nginx 实施，所以 Django 的 `SECURE_SSL_REDIRECT=False` 是有意配置，其部署检查提示需结合边界实测判断。

## 内部服务及验收

本机就绪检查仍访问 loopback Gunicorn 的 `/api/website`。为兼容 JudgeServer 的内部心跳，Nginx 对 `/api/judge_server_heartbeat`（可带末尾 `/`）保留 HTTP 入口，仍需原有 Token 鉴权；**公网网关应屏蔽这个 HTTP 例外，心跳只允许可信内部网络，跨网络则使用受信任证书的 HTTPS**。这不允许学生或管理员的其他 API 走明文 HTTP。

上线前检查：正式域名和证书链；HTTP→HTTPS；登录 Session 与 CSRF Cookie 的 Secure 属性；HTTPS 下真实 CSRF 请求；HTML/静态/API 的 HSTS；伪造代理头无效；就绪检查和真实心跳可用。首次启用 HSTS 后先观察 1 小时策略，未验证所有子域前不启用 includeSubDomains/preload。

该配置尚不能替代实际生产入口验证。真实域名、TLS 终止位置与服务配置由部署环境提供，密钥不写入仓库。
