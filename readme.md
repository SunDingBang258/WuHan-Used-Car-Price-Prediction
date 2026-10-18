从dev分支创建新的feature/xx 来完成其他模块

# 武汉二手车价格预测 —— 参数录入 + 价格预测

用户在前端录入二手车参数，后台查静态对照表补出模型特征，调用训练好的模型估价并存库。
训练与实验跟踪在 `ml/` 下，模型产物 `app/model.joblib` 随代码一起提交。

## 目录结构

```
.
├── .github/workflows/        4 条流水线, 对应 feature → dev → staging → main
│   ├── 01-feature-ci.yml
│   ├── 02-dev-ci.yml
│   ├── 03-staging-deploy.yml
│   └── 04-main-release.yml
├── app/
│   ├── config.py             配置(环境变量 + 自动加载 .env)
│   ├── database.py           ★ MySQL 的唯一配置入口, 全项目复用
│   ├── models.py             ORM 模型(cars 表)
│   ├── schemas.py            请求/响应校验
│   ├── crud.py               数据访问
│   ├── reference.py          品牌/车系 → ID+查表特征(读 reference.json)
│   ├── reference.json        静态对照表(30 品牌 / 279 车系)
│   ├── predictor.py          加载 model.joblib 做估价
│   ├── model.joblib          训练好的模型(由 ml/train.py 产出)
│   ├── main.py               应用装配
│   └── routers/
│       ├── cars.py           JSON API(含 POST /api/predict)
│       └── pages.py          HTML 页面
├── ml/                       训练与实验跟踪
│   ├── train.py              训练脚本(调 MLflow 记录)
│   ├── data_pipeline.py      数据清洗 + 导出对照表(默认 v2, `--v1` 产出第一版)
│   ├── configs/              baseline.yaml / tuned.yaml
│   ├── registry/             current_model.md(哪个模型是生产版)
│   ├── README_data.md  README_experiments.md  PROVENANCE.md
├── templates/                Jinja2 页面
├── static/style.css          样式
├── tests/                    测试(按 CI 阶段分目录)
├── Dockerfile
├── docker-compose.yml        MySQL + 应用编排(已显式指定 name, 见文件注释)
├── .dockerignore             构建上下文排除 data/ 等, 避免把凭据与大数据打进镜像
├── requirements.txt          运行时依赖(含推理用的 scikit-learn)
├── requirements-dev.txt      测试 + 静态检查依赖 —— CI 装这个
├── requirements-ml.txt       训练/实验跟踪依赖 —— 只有 ml/ 下的脚本需要
├── ruff.toml                 静态检查规则集
├── DEPLOYMENT.md             staging / production 怎么部署、要配哪些 secrets
└── .env.example              环境变量样例(复制成 .env 后填写)
```

项目里**没有 pytest.ini**：测试只用了 `skipif` 这类内置 marker，不需要注册。

> ⚠️ `mlflow` / `dagshub` 刻意放在 `requirements-ml.txt`，不放 `requirements-dev.txt`。
> 它们会拉进约 85 个连锁依赖（graphene、botocore、boto3、alembic、protobuf…），
> 实测完整安装集从 **36 个包涨到 121 个包**，CI 的 `pip install` 步骤会因此多跑好几分钟，
> 而 CI 的测试根本不 import 它们。

## 本地运行

```bash
pip install -r requirements-dev.txt

# 方式一: 用 docker-compose 起 MySQL + 应用(无需 .env)
docker compose up --build
# 打开 http://127.0.0.1:8000

# 方式二: 用你自己已有的 MySQL
cp .env.example .env          # 填好 DB_USER / DB_PASSWORD / DB_NAME
uvicorn app.main:app --reload --port 8000
```

`.env` 会被自动加载（`app/config.py` 里的 `load_dotenv`），**不需要手动 export**；
真实环境变量优先级更高、不会被 `.env` 覆盖——CI 与容器正是靠这一点直接注入。

数据库连接信息**没有任何兜底默认值**：没配就会在启动时立刻失败，
并明确列出缺哪几个变量，而不是拿一个猜的账号去连库、把问题推到更难查的地方。

接口文档: <http://127.0.0.1:8000/docs>

## MySQL 配置

集中在 `app/config.py`(读取环境变量)与 `app/database.py`(引擎/会话/依赖)两个文件，
业务代码只依赖 `Depends(get_db)`，**不直接拼连接串**。换库或换地址只改环境变量或 `.env`。

| 环境变量 | 必填 | 说明 |
|---|---|---|
| `DB_HOST` | ✅ | MySQL 地址 |
| `DB_PORT` | ✅ | 端口 |
| `DB_USER` | ✅ | 用户名 |
| `DB_PASSWORD` | ✅ | 密码 |
| `DB_NAME` | ✅ | 库名(需为 utf8mb4) |
| `DB_CHARSET` | — | 默认 `utf8mb4`，必须 utf8mb4 才能存 emoji |
| `DATABASE_URL` | — | 直接给完整连接串；设了它就忽略上面的分项 |

二选一：要么把 `DB_HOST`/`DB_PORT`/`DB_USER`/`DB_PASSWORD`/`DB_NAME` 五项都填上，
要么只给一条 `DATABASE_URL`。

## 接口

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/` | 首页: 录入表单 + 列表 |
| POST | `/cars` | 表单提交新增 |
| GET | `/cars/{id}/edit` | 编辑页 |
| POST | `/cars/{id}/edit` | 表单提交修改 |
| POST | `/cars/{id}/delete` | 表单提交删除 |
| GET | `/api/health` | 存活探针(不碰数据库) |
| GET | `/api/health/db` | 数据库探针(连不上返回 503) |
| GET | `/api/cars` | 列表，支持 `brand` / `city` / `skip` / `limit` |
| POST | `/api/cars` | 新增 |
| GET/PUT/PATCH/DELETE | `/api/cars/{id}` | 单条查询/更新/删除 |

## 测试

测试**与程序读同一套环境变量**，跑在同一个数据库上——没有单独的测试连接串，
也没有为了脱离数据库而写的替身代码。CI 的数据库由 workflow 的 `services.mysql` 提供。

> ⚠️ 用到数据库的测试会在开始前清空 `cars` 表，所以**请指向一个可丢弃的库**：

```bash
export DB_NAME=car_predict_test      # PowerShell: $env:DB_NAME='car_predict_test'
pytest                               # 全量
pytest tests/stage_feature           # 只跑某一阶段
```

测试按 CI 阶段分目录存放，跑某一阶段的测试就是跑对应目录。

| 目录 | 覆盖内容 |
|---|---|
| `tests/stage_feature/` | **配置与数据层**：连接串拼接、缺配置报错、引擎方言、健康探针、CRUD、名称查表 |
| `tests/stage_dev/` | **接口与页面**：JSON API 全流程与校验、HTML 表单渲染/提交/编辑/删除 |
| `tests/stage_staging/` | **应用冒烟**：首页、健康探针、CRUD 全链路串跑(TestClient, 进程内) |

`tests/stage_feature/test_config.py` 是纯配置逻辑测试，不需要数据库也能单独跑。

## 分支与流水线

> 课程文档里提到的分支链路是：**feature 分支 → dev 分支 → staging 分支 → main 主分支**。
> 这四个分支已创建好，可以直接切换（原 `readme.md` 的记录保留于此）。

| 分支 / 事件 | 流水线 | 做什么 | 跑哪些测试 |
|---|---|---|---|
| push `feature/**` | `01-feature-ci.yml` | ruff + 构建镜像 + 数据层测试 | `tests/stage_feature` |
| **PR → `dev`** | `01-feature-ci.yml` | ruff + 构建镜像 + **全量测试** | 全部 |
| push `dev` | `02-dev-ci.yml` | ruff + 构建镜像 + 全量测试 | 全部 |
| **PR → `staging`** | `02-dev-ci.yml` | ruff + 构建镜像 + 全量测试 | 全部 |
| push `staging` | `03-staging-deploy.yml` | 生成 staging `.env` → 起真实 MySQL+应用 → curl 验证 → 冒烟测试 | `tests/stage_staging` |
| **PR → `main`** | `04-main-release.yml` | ruff + 构建镜像 + 全量测试 | 全部 |
| push `main` | `04-main-release.yml` | 全量测试 + 生成生产 `.env` + 构建生产镜像(部署占位) | 全部 |
| tag `v*` | `04-main-release.yml` | 上述 + 推镜像到 Docker Hub + 发 GitHub Release | 全部 |

**课程要求：PR 到受保护分支必须 ① 跑全量测试 ② 跑 lint ③ 构建 Docker 镜像** ——
`01` / `02` / `04` 三个文件都覆盖了这三项。

`03-staging-deploy.yml` 里真正验证「跑起来的容器」的是两个 `curl` 步骤
（`/api/health` 就绪等待、`/api/health/db` 连通性）；`tests/stage_staging/` 是进程内测试，
验证的是代码本身，不经过容器。

部署细节（要配哪些 secrets、怎么接真实部署）见 [`DEPLOYMENT.md`](DEPLOYMENT.md)。

## 后续计划

1. 用 Alembic 做数据库迁移，替掉 `AUTO_CREATE_TABLES`。
2. 把 `04-main-release.yml` 的 `deploy-production` 从占位换成真实部署（SSH / K8s）。
3. 扩充数据集版本到 v3（例如按发布时间切分）并对比模型效果。
