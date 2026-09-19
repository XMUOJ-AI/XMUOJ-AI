# XMUOJ-AI 前端

学生端和管理端共用一个 Vue 3 项目，通过两个 HTML 入口分别加载。当前目录与开发入口以[根 README](../README.md)为准；本项目源自 QingdaoU OnlineJudgeFE。

- 学生端：View UI Plus，入口 `/`。
- 管理端：Element Plus，入口 `/admin/`，登录页 `/admin/login`。
- Vue Router 4、Vuex 4、Vue I18n 11；Vite 构建。
- 保留 CodeMirror 5、ECharts 3、Simditor 核心及旧图标、主题，使用 Vue 3 封装保持现有页面表现。

## 开发

使用 Node.js 24、npm 11+，在本目录执行：

```bash
npm ci
TARGET=http://127.0.0.1:8000 npm run dev
```

默认端口为 `8080`，通过 `PORT=8090 npm run dev` 可更换端口。`TARGET` 控制 `/api` 和 `/public` 的后端代理，默认指向 `http://127.0.0.1:8000`。不再需要 DLL 构建或 OpenSSL 兼容参数。

不连接后端的页面演示：

```bash
npm run dev:mock
```

Mock 模式只使用本地样例，提交与 AI 结果均为模拟。开发说明见[功能原型说明](docs/ai-feature-prototypes.md)。

## 检查与构建

```bash
npm run lint
npm test
npm run build
npm run preview
```

生产产物为 `dist/index.html`、`dist/admin/index.html` 和 `dist/static/`。生产构建始终关闭 Mock；`preview` 仅用于本地检查产物。构建时可设置 `STATIC_CDN_HOST` 指定静态资源 CDN，`USE_SENTRY=1` 开启已有 Sentry 接入和 source map。

实际部署需保留学生端、管理端的 HTML 回退及 `/api`、`/public` 路径。`build.sh` 是显式容器部署脚本：安装锁定依赖、构建、复制到 `oj-backend:/app/`，然后打开容器 shell；它不是日常开发命令。

## 兼容与维护

浏览器范围：Chrome、Edge、Firefox 最近两个版本及 Safari 16.4+，不支持 IE。依赖版本以 `package.json`、`package-lock.json` 为准，统一使用 npm。

Vue 3 迁移和后续调整需同时验证学生端、管理端及四项 AI Mock 功能；验收场景见[测试矩阵](docs/vue3-test-matrix.md)。代码入口与职责见[代码导览](CODE_WIKI.md)。[instructions.md](instructions.md)保留已标注的历史部署记录。

本次迁移结果、回归修复、验收证据和尚未完成的完整截图验收见[迁移记录](docs/vue3-migration.md)。

项目遵循 [MIT 许可证](LICENSE)。保留的图标和编辑器依赖许可证分别位于 `src/assets/legacy-icons/`、`vendor/`。
