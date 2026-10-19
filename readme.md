# 武汉二手车价格预测

录入一台二手车的品牌、车系、车龄和里程，用训练好的模型估算价格，参数和结果一起写进 MySQL。

## 技术栈

后端 FastAPI + SQLAlchemy，数据库 MySQL 8.4，页面用 Jinja2 服务端渲染。

训练部分在 `ml/` 目录，用 scikit-learn 的 HistGradientBoosting 做回归。数据用 DVC 管版本（远端在 Azure），实验用 MLflow 记录（记录到 DagsHub），部署走 Docker 和 GitHub Actions。

## 目录结构

```
app/
  main.py         应用入口
  config.py       配置，读环境变量和 .env
  database.py     数据库连接、会话、建表
  models.py       cars 表
  schemas.py      请求和响应的校验规则
  crud.py         增删改查
  reference.py    品牌车系对照表
  reference.json  对照表数据，30 个品牌 279 个车系
  predictor.py    加载 model.joblib 做预测
  model.joblib    训练好的模型
  routers/
    cars.py       JSON API
    pages.py      HTML 页面

ml/
  train.py            训练脚本，调 MLflow 记录
  data_pipeline.py    数据清洗，产出数据集和 reference.json
  configs/            baseline.yaml 和 tuned.yaml
  registry/           current_model.md，记录当前生产模型

templates/    Jinja2 页面
static/       样式
tests/        测试，按 CI 阶段分成三个目录
```

## 运行

先装依赖：

```bash
pip install -r requirements-dev.txt
```

方式一，用 docker compose 起 MySQL 和应用，不需要 .env：

```bash
docker compose up --build
```

方式二，连自己已有的 MySQL：

```bash
cp .env.example .env          # 填好 DB_USER / DB_PASSWORD / DB_NAME
uvicorn app.main:app --reload --port 8000
```

打开 http://127.0.0.1:8000 用页面，接口文档在 http://127.0.0.1:8000/docs。

## 环境变量

| 变量 | 必填 | 说明 |
|---|---|---|
| `DB_HOST` | 是 | MySQL 地址 |
| `DB_PORT` | 是 | 端口 |
| `DB_USER` | 是 | 用户名 |
| `DB_PASSWORD` | 是 | 密码 |
| `DB_NAME` | 是 | 库名，utf8mb4 |
| `DB_CHARSET` | 否 | 默认 utf8mb4 |
| `DATABASE_URL` | 否 | 完整连接串，设了就忽略上面五项 |

`DB_HOST` 到 `DB_NAME` 五项要么都填，要么只给一条 `DATABASE_URL`。这几项没有默认值，缺了启动时直接报错并列出缺哪个。

`.env` 在 `app/config.py` 里自动加载，不用手动 export。真实环境变量优先级更高，CI 和容器就是靠这点直接注入的。

## 接口

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/` | 首页，录入表单和已保存列表 |
| POST | `/cars` | 表单提交新增，成功后跳到结果页 |
| GET | `/cars/{id}` | 估价结果页 |
| GET / POST | `/cars/{id}/edit` | 编辑页 / 提交修改 |
| POST | `/cars/{id}/delete` | 删除 |
| GET | `/api/health` | 存活探针，不查库 |
| GET | `/api/health/db` | 数据库探针，连不上返回 503 |
| GET | `/api/cars` | 列表，支持 `brand` / `skip` / `limit` |
| POST | `/api/cars` | 新增 |
| POST | `/api/predict` | 只估价，不写库 |
| GET / PUT / PATCH / DELETE | `/api/cars/{id}` | 单条查询 / 更新 / 删除 |

## 测试

测试连的是环境变量里配的那个库，CI 里由 workflow 的 `services.mysql` 提供。

用到数据库的测试会先清空 `cars` 表，所以把 `DB_NAME` 指到一个可以丢弃的库再跑：

```bash
export DB_NAME=car_predict_test      # PowerShell: $env:DB_NAME='car_predict_test'
pytest                                # 全跑
pytest tests/stage_feature            # 只跑某一阶段
```

一共 39 个测试，按阶段分三个目录：

- `tests/stage_feature/` 配置拼接、缺配置报错、CRUD、健康探针
- `tests/stage_dev/` JSON API、HTML 页面、价格预测
- `tests/stage_staging/` 冒烟，全链路串跑

## 分支和流水线

四个分支，合并路径是 feature → dev → staging → main。

| 事件 | 流水线 | 做什么 |
|---|---|---|
| push `feature/**` | `01-feature-ci.yml` | ruff + 构建镜像 + 数据层测试 |
| PR → `dev` | `01-feature-ci.yml` | ruff + 构建镜像 + 全量测试 |
| push `dev` | `02-dev-ci.yml` | ruff + 构建镜像 + 全量测试 |
| PR → `staging` | `02-dev-ci.yml` | 同上 |
| push `staging` | `03-staging-deploy.yml` | 生成 staging .env，起真实容器，curl 探活，跑冒烟 |
| PR → `main` | `04-main-release.yml` | ruff + 构建镜像 + 全量测试 |
| push `main` | `04-main-release.yml` | 全量测试，生成生产 .env，构建生产镜像 |
| tag `v*` | `04-main-release.yml` | 上面这些，再加推镜像到 Docker Hub 和发 Release |

部署要配哪些 secrets、怎么接真实部署，见 [DEPLOYMENT.md](DEPLOYMENT.md)。

## 其它文档

- [ml/README_data.md](ml/README_data.md) 数据来源、清洗规则、v1 和 v2 的区别
- [ml/README_experiments.md](ml/README_experiments.md) 两组实验的指标对比和选型理由
- [ml/PROVENANCE.md](ml/PROVENANCE.md) 从爬虫到线上模型的完整链条
- [ml/registry/current_model.md](ml/registry/current_model.md) 当前生产模型是哪个、怎么回滚

## 待办

- 用 Alembic 做数据库迁移，替掉 `AUTO_CREATE_TABLES`
- `04-main-release.yml` 里的 `deploy-production` 还是占位，要接真实部署
- 数据集补一个 v3，比如按发布时间切分，再对比模型效果
