# AGENTS.md

## 项目简介

XMUOJ-AI 是一个在线编程评测系统，仓库包含前端和后端代码，基于 OnlineJudge 项目扩展。主要功能包括题目浏览、代码提交、比赛、排名以及用户和题目管理。

前端采用 Vue 2、Vue Router、Vuex 和 Webpack 3；后端采用 Django 3.2、Django REST Framework，通过 PostgreSQL 保存数据，使用 Redis 和 Dramatiq 支撑缓存及后台任务。执行代码的判题服务器和判题沙箱属于外部配套组件，不包含在此仓库中。

## 项目简要导览

- `README.md`：整个项目的说明、环境前提和开发入口。
- `frontend/`：前端项目；`src/pages/oj/` 为用户页面，`src/pages/admin/` 为管理页面，`src/store/` 为状态管理，`config/` 和 `build/` 为开发与构建配置。
- `backend/`：后端项目；`oj/` 为 Django 配置，`account/`、`problem/`、`contest/`、`submission/` 分别处理用户、题目、比赛和提交，`judge/` 对接判题，`utils/` 为公共工具。
- `backend/deploy/`：依赖清单及服务部署配置；`backend/data/` 为运行数据目录。
- 前后端各自的 README 和其他文档保留组件及历史上游说明；当前仓库的目录与操作入口以根 README 为准。

## 常用命令

命令必须在表格指定的目录执行。前端使用现有 npm scripts，仓库同时保留了历史 `yarn.lock`；不要仅因目录整理而切换包管理器或更新依赖。

| 工作目录 | 命令 | 用途 |
| --- | --- | --- |
| `frontend/` | `npm install --legacy-peer-deps` | 安装前端依赖 |
| `frontend/` | `NODE_ENV=development npm run build:dll` | 首次开发前构建 DLL |
| `frontend/` | `TARGET=http://127.0.0.1:8000 npm run dev` | 启动前端并代理后端接口 |
| `frontend/` | `NODE_ENV=production npm run build:dll && npm run build` | 构建生产静态资源 |
| `frontend/` | `npm run lint` | 检查前端代码 |
| `backend/` | `python -m pip install -r deploy/requirements.txt` | 在已激活的虚拟环境中安装后端依赖 |
| `backend/` | `python manage.py migrate` | 执行数据库迁移 |
| `backend/` | `python manage.py runserver 127.0.0.1:8000` | 启动后端开发服务 |
| `backend/` | `python manage.py rundramatiq` | 启动后台任务工作进程 |
| `backend/` | `flake8 --statistics .` | 检查后端代码 |
| `backend/` | `python manage.py test problem --settings=oj.settings` | 运行指定模块测试；按修改范围替换 `problem` |
| `backend/` | `python manage.py test --settings=oj.settings` | 运行全部 Django 测试 |
| 仓库根目录 | `docker build -f backend/Dockerfile -t xmuoj-ai .` | 构建包含前端产物的后端镜像；需先构建 `frontend/dist/` |

后端运行和测试前需配置 PostgreSQL、Redis 及 `backend/data/config/secret.key`，详见根 README。现有 `run_test.py` 会组合 lint 和测试，但未可靠传递失败退出码；需要判断检查是否通过时，直接使用表中的 lint 和测试命令。

## 解释代码

Use plain language over jargon, and reference technical details only to the degree that it helps illustrate an idea or your work to the user. Communicate complex concepts in a clear and cohesive manner, and calibrate your writing to the level of background knowledge assumed from the user's prompt and context.

## 测试

Do not write tests for reversible, low-impact changes that mirror the implementation. If you do choose to verify your work with tests, make sure that the tests are meaningful and necessary to verify implementation.

Run tests appropriate to the change and complete required checks. Once those pass, broaden or repeat testing only when new changes, failures, or unresolved concerns justify it; otherwise, continue toward completing the task.
