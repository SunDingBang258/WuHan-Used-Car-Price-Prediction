# 部署说明

本文说明代码如何从一次提交走到 staging 和 production，以及每个环境需要配什么。

## 全景

```
开发者本地
   │ git push feature/xxx
   ▼
┌──────────────────────────────────────────────────────────────┐
│ 01 · feature 快速校验    (push feature/** | PR → dev)        │
│   ruff check → docker build → pytest                         │
│   push 时跑 tests/stage_feature; PR 时跑全量                  │
└──────────────────────────────────────────────────────────────┘
   │ PR 合并到 dev
   ▼
┌──────────────────────────────────────────────────────────────┐
│ 02 · dev 集成校验        (push dev | PR → staging)           │
│   ruff check → docker build → pytest tests  (全量)           │
└──────────────────────────────────────────────────────────────┘
   │ PR 合并到 staging
   ▼
┌──────────────────────────────────────────────────────────────┐
│ 03 · staging 部署与冒烟  (push staging)                       │
│   ① 用 staging secrets 生成 .env                              │
│   ② docker compose up -d --build   (MySQL + 应用)             │
│   ③ curl /api/health, /api/health/db  ← 打真实容器            │
│   ④ pytest tests/stage_staging      ← 进程内冒烟              │
│   ⑤ docker compose down -v                                    │
└──────────────────────────────────────────────────────────────┘
   │ PR 合并到 main
   ▼
┌──────────────────────────────────────────────────────────────┐
│ 04 · main 发布           (push main / tags v* / PR → main)    │
│                                                                 │
│   job verify          ruff check → docker build → pytest 全量  │
│   job build-and-push  ★ 仅打 v* 标签时                        │
│                        登录 Docker Hub → 推 latest + sha-<commit>│
│   job release         ★ 仅打 v* 标签时  创建 GitHub Release    │
│   job deploy-production ★ 仅 push main                          │
│                        用 production secrets 生成 .env         │
│                        → 构建生产镜像 → 部署(占位, 待接入)      │
└──────────────────────────────────────────────────────────────┘
```

## 分支 → 流水线 → 触发条件

| 分支 | 流水线 | 触发事件 | 跑什么 |
|---|---|---|---|
| `feature/**` | `01-feature-ci.yml` | push | ruff + docker build + `tests/stage_feature` |
| `dev`（PR 目标） | `01-feature-ci.yml` | pull_request | ruff + docker build + **全量测试** |
| `dev` | `02-dev-ci.yml` | push | ruff + docker build + 全量测试 |
| `staging`（PR 目标） | `02-dev-ci.yml` | pull_request | ruff + docker build + 全量测试 |
| `staging` | `03-staging-deploy.yml` | push | 起真实容器 → curl 验证 → 冒烟测试 |
| `main`（PR 目标） | `04-main-release.yml` | pull_request | ruff + docker build + 全量测试 |
| `main` | `04-main-release.yml` | push | 全量测试 + 生产 .env + 构建(部署占位) |
| tag `v*` | `04-main-release.yml` | push | 全量测试 + 推镜像到 Docker Hub + 发 Release |

**课程要求的三项（PR 到受保护分支必须全做）**：`ruff check` / 全量测试 / `docker build` ——
`01`、`02`、`04` 三个文件都覆盖了。

## staging 如何部署

`03-staging-deploy.yml` 用 `docker compose` 在本机拉起**真实的 MySQL + 应用容器**，
然后从容器外部用 curl 验证 HTTP，最后跑进程内冒烟测试。

所需 secrets（配在 **Settings → Environments → staging**）：

| secret | 用途 |
|---|---|
| `STAGING_DB_USER` | 应用连 MySQL 的用户 |
| `STAGING_DB_PASSWORD` | 上面的密码 |
| `STAGING_DB_NAME` | 库名 |
| `STAGING_MYSQL_ROOT_PASSWORD` | MySQL 容器的 root 密码 |

工作流会把这些值写进 `.env`，`docker-compose.yml` 用 `${MYSQL_USER:-carpredict}` 这类写法读取。

**没配 secret 也能跑**：`${VAR:-默认}` 会退回默认值（`carpredict` / `car_predict`），
冒烟测试因此不会因为缺 secret 而红。真要区分环境时再配。

端口约定：compose 把 MySQL 的 3306 映射到宿主机 **13306**（避开本机已装的 MySQL）。
容器内的应用用 `DB_HOST=mysql:3306`；runner 上的 pytest 用 `127.0.0.1:13306`。

## production 如何部署

`04-main-release.yml` 的 `deploy-production` job：

1. 用 **production** 环境的 secrets 生成 `.env`
2. `docker build -t wuhan-used-car-price-prediction:production .`
3. 部署步骤目前是**占位**（`echo TODO`），需要接入真实方式

所需 secrets（配在 **Settings → Environments → production**），建议同时开启
**Required reviewers** 让人工审批：

| secret | 用途 |
|---|---|
| `PROD_DB_HOST` / `PROD_DB_PORT` | 生产 MySQL 地址 |
| `PROD_DB_USER` / `PROD_DB_PASSWORD` | 生产库账号 |
| `PROD_DB_NAME` | 生产库名 |
| `PROD_MYSQL_ROOT_PASSWORD` | 生产 MySQL root 密码 |

### 接入真实部署

把 `deploy-production` 的最后一步换成下面任一种。

**SSH 到服务器拉镜像跑**（配合 tag 触发推送的镜像）：

```yaml
- name: 部署到服务器
  run: |
    ssh "${{ secrets.PROD_SSH_USER }}@${{ secrets.PROD_SSH_HOST }}" "
      docker pull ${{ secrets.DOCKERHUB_USERNAME }}/wuhan-used-car-price-prediction:${{ github.ref_name }} &&
      docker rm -f car-predict || true &&
      docker run -d --name car-predict --env-file /srv/car-predict/.env \
        -p 8000:8000 \
        ${{ secrets.DOCKERHUB_USERNAME }}/wuhan-used-car-price-prediction:${{ github.ref_name }}
    "
```

**Kubernetes**：

```yaml
- run: |
    kubectl set image deployment/car-predict \
      app=${{ secrets.DOCKERHUB_USERNAME }}/wuhan-used-car-price-prediction:${{ github.ref_name }}
```

## 镜像

推送到 Docker Hub：`<DOCKERHUB_USERNAME>/wuhan-used-car-price-prediction`

每次打 `v*` 标签推两个 tag：

| tag | 含义 |
|---|---|
| `latest` | 永远指向最近一次发布 |
| `sha-<commit>` | 对应具体 commit，可精确回滚 |

镜像里已经包含：应用代码、`templates/`、`static/`、`app/model.joblib`（1.5 MB）、
`app/reference.json`。**运行不依赖源码目录，也不需要在容器里训练**。

运行需要外部 MySQL：

```bash
docker run -p 8000:8000 --env-file .env \
  <user>/wuhan-used-car-price-prediction:latest
```

## 需要的仓库/环境 secrets 汇总

| 名称 | 作用域 | 用途 |
|---|---|---|
| `DOCKERHUB_USERNAME` | 仓库 | 登录 Docker Hub + 拼镜像名 |
| `DOCKERHUB_TOKEN` | 仓库 | Docker Hub access token |
| `STAGING_*` | 环境 `staging` | 生成 staging `.env` |
| `PROD_*` | 环境 `production` | 生成 production `.env` |

## 本地等价操作

不想跑 CI 时，本地一条命令做同样的事：

```powershell
.\.venv\Scripts\ruff.exe check app tests ml      # 静态检查
.\.venv\Scripts\python.exe -m pytest tests -q    # 全量测试
docker compose up -d --build                     # 起 MySQL + 应用
docker compose down -v                           # 清理(连数据卷)
```
