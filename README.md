# XMUOJ-AI

在线编程评测系统，包含用户端、管理端和后端服务，支持题目浏览、代码提交、比赛与排名、用户和题目管理。代码基于 OnlineJudge 项目扩展，由 XMUOJ-AI 组织维护。

## 目录结构

```text
XMUOJ-AI/
├── README.md              # 项目说明
├── AGENTS.md              # AI 协作规则
├── .gitignore
├── .dockerignore          # 仓库根目录的 Docker 构建上下文规则
├── frontend/              # Vue 前端
│   ├── README.md
│   ├── package.json
│   ├── config/
│   ├── build/
│   └── src/
└── backend/               # Django 后端
    ├── README.md
    ├── README-CN.md
    ├── manage.py
    ├── Dockerfile
    ├── oj/
    └── deploy/
```

前后端通过 HTTP API 通信。后端依赖 PostgreSQL、Redis；完整判题还需要独立部署判题服务器及沙箱，此仓库不包含这两个组件，也不包含完整的 Docker Compose 部署配置。

## 技术与环境

- 前端：Vue 2、Vuex 3、Webpack 3，命令定义在 `frontend/package.json`。
- 后端：Django 3.2.25、Django REST Framework 3.14、Dramatiq，依赖清单为 `backend/deploy/requirements.txt`。
- 后端 Dockerfile 当前采用 Python 3.12 Alpine 基础镜像。

这是包含历史依赖的项目。前端上游 README 指定 Node.js 8.12.0，而现有本地部署脚本使用 `--openssl-legacy-provider` 兼容选项；这些信息不构成所有 Node.js 版本均可使用的保证。本次目录整理未完成依赖安装或运行环境兼容性验证。仓库保留历史 `yarn.lock`，以下命令沿用现有 npm 脚本。

## 前端开发

在仓库根目录执行：

```bash
cd frontend
npm install --legacy-peer-deps
NODE_ENV=development npm run build:dll
TARGET=http://127.0.0.1:8000 npm run dev
```

`TARGET` 指向后端服务。首次开发及 DLL 依赖变化后需要重新执行 `build:dll`。若所用 Node.js 版本因旧版 Webpack 出现 OpenSSL 兼容错误，可参照 `redeploy_local.sh` 中的 `NODE_OPTIONS` 设置处理。

生产构建和代码检查，在 `frontend/` 执行：

```bash
NODE_ENV=production npm run build:dll
npm run build
npm run lint
```

构建产物位于 `frontend/dist/`。

## 前端 Mock 预览

无需启动后端，可在安装前端依赖后执行：

```bash
cd frontend
npm run dev:mock
```

启动器会在缺少 DLL 时自动构建，并为新版 Node 配置 Webpack 3 所需的 OpenSSL 兼容选项。默认访问 `http://127.0.0.1:8080`，端口被占用时以终端输出为准。

Mock 模式默认登录模拟学生，提供首页公告、三道示例题、题目筛选、提交列表与详情。提交只生成固定结果的内存演示记录，不执行代码、不连接真实后端；重启后恢复初始数据。其他未实现的接口会明确报错。退出服务用 `Ctrl+C`。

## 后端开发

在仓库根目录创建并激活虚拟环境，然后安装依赖：

```bash
python3 -m venv .venv
source .venv/bin/activate
cd backend
python -m pip install -r deploy/requirements.txt
```

安装 `psycopg2`、Pillow 等依赖可能需要本机编译工具和相应系统库。

启动前准备 PostgreSQL 数据库和 Redis。开发配置在 `backend/oj/dev_settings.py`，支持以下环境变量：

| 环境变量 | 默认值 |
| --- | --- |
| `POSTGRES_HOST` / `POSTGRES_PORT` | `127.0.0.1` / `5432` |
| `POSTGRES_DB` / `POSTGRES_USER` / `POSTGRES_PASSWORD` | `onlinejudge` |
| `REDIS_HOST` / `REDIS_PORT` | `127.0.0.1` / `6379` |

默认使用开发配置；`OJ_ENV=production` 会切换为生产配置。开发默认凭据仅用于本地环境。

在 `backend/` 生成本地密钥文件（已有文件会保留），然后迁移并启动：

```bash
python - <<'PY'
from pathlib import Path
import secrets
path = Path('data/config/secret.key')
path.parent.mkdir(parents=True, exist_ok=True)
if not path.exists():
    path.write_text(secrets.token_urlsafe(48))
    path.chmod(0o600)
PY
python manage.py migrate
python manage.py runserver 127.0.0.1:8000
```

后台任务需要在另一个已激活虚拟环境、使用相同配置的终端中运行 `python manage.py rundramatiq`。实际判题还需配置外部判题服务器。

历史脚本 `backend/init_db.sh` 会删除并重建同名开发容器，且映射到 PostgreSQL `5435`、Redis `6380`；这些端口与开发配置默认值不同，不应直接当作无副作用的初始化命令。

## 检查与测试

前端在 `frontend/` 执行 `npm run lint`。后端在依赖、密钥和数据库等环境就绪后，于 `backend/` 执行：

```bash
flake8 --statistics .
python manage.py test problem --settings=oj.settings
# 需要全量检查时：
python manage.py test --settings=oj.settings
```

将 `problem` 替换为本次修改涉及的 Django 模块。测试使用数据库时，数据库用户需具备创建测试数据库的权限。历史 `run_test.py` 的退出码不能可靠反映检查失败，因此这里列出独立命令。

## 镜像与部署

先完成前端生产构建，再在仓库根目录执行：

```bash
docker build -f backend/Dockerfile -t xmuoj-ai .
```

Dockerfile 从根构建上下文复制 `backend/` 和 `frontend/dist/`。镜像构建不等于完整部署，数据库、Redis、持久化数据及判题组件仍需单独配置。

`frontend/redeploy_local.sh` 用于更新已有部署，会替换容器中的前端产物并重启服务。使用时应通过 `COMPOSE_FILE` 指定实际的外部 Compose 文件；默认查找仓库下 `OnlineJudgeDeploy/docker-compose.yml`，该目录不随本仓库提供。

## 项目协作文档

以下链接来自飞书「AI领航员」群聊，访问权限以飞书文档设置为准。

- [项目共享文件夹](https://mcngekjmg24m.feishu.cn/drive/folder/DS9Efifedlci7Jd6DovcBv0Wnjd?from=from_copylink)
- [技术路线与功能实现设计](https://mcngekjmg24m.feishu.cn/docx/VMLjdhgZQo5lS1xgUKNcbUKQnGb)
- [第一期讨论](https://mcngekjmg24m.feishu.cn/docx/DxtBdkz4son5enxFEtdcJJoDngt)

## 组件文档与来源

- [前端说明](frontend/README.md)
- [前端代码导览](frontend/CODE_WIKI.md)
- [后端中文说明](backend/README-CN.md)
- [后端英文说明](backend/README.md)
- [AI 协作规则](AGENTS.md)

组件文档保留上游项目名称和历史部署示例，旧目录和外部仓库示例不代表当前仓库结构。当前开发入口以本文为准，组件源码及许可文件保留在各自目录中。
