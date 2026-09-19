# 当前前端开发与部署

当前仓库前端已迁移到 Vue 3 + Vite，使用 Node.js 24、npm 11+。以下命令在 frontend/ 执行，完整说明见 [README](README.md)。

```bash
npm ci
TARGET=http://127.0.0.1:8000 npm run dev
```

纯前端演示使用 npm run dev:mock；日常检查使用 npm run lint 和 npm test；生产产物通过 npm run build 输出到 dist/。无需 DLL 构建，生产构建始终关闭 Mock。

build.sh 是显式部署脚本：使用锁定依赖构建，将 dist/ 复制到 oj-backend 容器的 /app/，随后打开容器 shell。运行它会操作该容器；仅构建请用 npm run build。当前项目与后端部署入口以[根 README](../README.md)为准。

---

> 下方为 2018 年上游环境的原始安装与后端运维记录，仅供历史参考。Ubuntu、Docker、仓库路径、数据库及容器操作均未作为本次 Vue 3 迁移重新验证；不要将其视为当前项目安装步骤。旧前端和 Node 8 指令已由上方当前说明替代。

# 历史上游安装与后端运维记录

> ### by sway 2018-12-21 ###

## 系统安装及更新

1. 安装操作系统：ubuntu 18.04 server LTS，全部用默认安装，无需特意设置，安装后重启；
2. 修改源：`sudo vi /etc/apt/sources.list`
   追加4行：
   ```
   deb http://cn.archive.ubuntu.com/ubuntu bionic main multiverse restricted universe
   deb http://cn.archive.ubuntu.com/ubuntu bionic-updates main multiverse restricted universe
   deb http://cn.archive.ubuntu.com/ubuntu bionic-security main multiverse restricted universe
   deb http://cn.archive.ubuntu.com/ubuntu bionic-proposed main multiverse restricted universe
   ```
3. `sudo apt-get update`
4. `sudo apt-get upgrade`

## 环境配置

1. `sudo apt-get install -y python3-pip`
2. `sudo apt-get install -y git`
3. `pip3 install docker-compose`
4. `sudo snap install docker`
   
## 首次安装OJ

1. `git clone -b 2.0 https://github.com/QingdaoU/OnlineJudgeDeploy.git && cd OnlineJudgeDeploy`
2. root用户执行：`docker-compose up`  
   非root用户执行：`sudo -E docker-compose up` （一定要-E参数，否则会出现数据丢失，原因未知）

## 更新OJ

1. `cd OnlineJudgeDeploy`
2. `sudo git pull`
3. `sudo docker-compose pull`
4. root用户执行：`docker-compose up –d`  
   非root用户执行：`sudo -E docker-compose up –d` （一定要-E参数，否则会出现数据丢失，原因未知）
  
## 后端二次开发

1. 首次拉取代码：`git clone https://github.com/shaohuihuang/OnlineJudge.git`  
   或者更新代码：`cd OnlineJudge && git pull`
2. `cd OnlineJudge`
3. `sudo docker cp ./ oj-backend:/app/`

## 数据库容器操作

+ 进入：`sudo docker exec -it oj-postgres /bin/sh`
+ 备份：`pg_dump -U onlinejudge -F t -f 1216.tar onlinejudge`
+ 还原：`pg_restore –c –U onlinejudge –d onlinejudge 1216.tar`

## 不同数据库版本之间的备份

前面的备份在postgres版本不同时貌似不能成功，需要改为如下方案：

### 准备活动

1. 备份为sql格式：`sudo docker exec -it oj-postgres pg_dumpall -c -U onlinejudge > 1221.sql`
2. 复制到容器内：`sudo docker cp 1221.sql oj-postgres:/`
3. 断开数据库连接：`sudo docker stop oj-backend`

### psql操作

1. 进入容器：`sudo docker exec -it oj-postgres /bin/sh`
2. 用onlinejudge身份进入postgres数据库：`psql -U onlinejudge -d postgres`
3. 删除旧库：`drop database onlinejudge;`
4. 创建新库：`create database onlinejudge;`
5. 退出库：`\q`
6. 导入sql：`psql -U onlinejudge -d onlinejudge < 1221.sql` 

## 增加编译语言（修改judge/languages.py文件后，需要重设配置）
1. `sudo docker exec -it oj-backend /bin/sh`
2. `python3 manage.py shell`
3. `from options.options import *`
4. `SysOptions.reset_languages()`
5. `exit()`
6. `exit`
