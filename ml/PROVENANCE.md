# 溯源（Provenance）

从爬虫到线上模型的完整链条，以及每一步的版本怎么定位。

## 链路

```
① 爬虫           data/爬虫/che168_crawler.py  --brand-pages N
                 品牌清单在 TARGET_BRANDS（30 个）
                          ↓
② 原始数据       data/爬虫/che168_wuhan_brands.csv          3222 条, 19 列
                 data/数据处理/che168_wuhan_cars.raw.csv    2239 条, 31 列
                          ↓
③ 数据流水线     ml/data_pipeline.py
                 · 合并去重（A 优先）
                 · 丢空 / 丢矛盾值 / 组过滤
                 · 补派生列 + 目标编码
                          ↓
④ 训练数据集     data/che168_wuhan_cars.csv    3141 条, 20 列   ← DVC 管理
                 data/che168_wuhan_cars.csv.dvc
                          ↓
⑤ 对照表         app/reference.json            30 品牌 / 279 车系
                 （同一条命令产出，应用运行时读）
                          ↓
⑥ 训练           ml/train.py --config configs/tuned.yaml
                          ↓
⑦ 模型记录       MLflow run  +  LoggedModel     ← DagsHub
                          ↓
⑧ 应用加载       app/model.joblib              1,546,617 字节
```

## 当前生产版本的全部版本号

| 项目 | 值 |
|---|---|
| 代码 commit | `61c2fa704c2e13ae503e21e797ab02ffa1b4f819` |
| 数据集 DVC hash = 实际 md5 | `99f0c71c43a3c3a57a4545c74a2bae75` |
| 数据集行数 / 字节 | 3141 / 793,683 |
| 配置文件 | `ml/configs/tuned.yaml` |
| MLflow run id | `5943ec07c33d4b49888d9507cce4de10` |
| MLflow LoggedModel | `m-ca29801c0a9d49e5b83ebaeabb651f4a` |
| 应用模型文件 | `app/model.joblib`（1,546,617 字节） |
| scikit-learn | 1.9.1 |
| MLflow | 3.17.1 |
| pandas / numpy | 3.0.6 / 2.5.4 |
| MLflow 追踪地址 | `https://dagshub.com/q13297638316/WuHan-Used-Car-Price-Prediction.mlflow` |

## 每一步怎么定位

**代码版本** —— 训练脚本自己记录：

```python
mlflow.set_tag("git_commit", sha)          # git rev-parse HEAD
mlflow.log_params({"git_commit": sha[:12]})
```

MLflow 还会自动打 `mlflow.source.git.commit` / `mlflow.source.git.branch` 两个 tag。

**数据版本** —— 同时记两份并交叉校验：

```python
actual = hashlib.md5(CSV.read_bytes()).hexdigest()   # 实际文件的 md5
recorded = re.search(r"md5:\s*(\S+)", DVC_FILE)      # .dvc 里记的
```

两者都会作为 param 记录（`dataset_md5` / `dataset_dvc_hash`）。**不一致时脚本会打印告警**——意思是 `dvc add` 忘了跑，`.dvc` 文件已过期。

**超参数** —— 配置文件全文进 param，同时把 yaml 原文件作为 artifact 存一份（`config/tuned.yaml`），这样即使以后配置改了也能还原当次的确切参数。

**指标** —— 5 折 CV 的均值进 metric，逐折明细作为 artifact（`cv_folds.json`）。

**制品** —— 三层都留了：

| 位置 | 内容 |
|---|---|
| `model/`（LoggedModel） | MLflow 3 的模型实体，带 signature、input_example、requirements |
| `model_file/model.joblib` | run 级制品，直接可下载 |
| `app/model.joblib` | 应用实际加载的，当 `save_to_app: true` 时写入 |

## 复现方式

```powershell
# 1) 数据集（从原始爬取重建，会覆盖 data/che168_wuhan_cars.csv）
.\.venv\Scripts\python.exe ml\data_pipeline.py

# 2) 从 DVC 拉回数据集（多人协作时用这个，不重建）
dvc pull

# 3) 训练（两个配置都跑一遍就复现出两个对比实验）
.\.venv\Scripts\python.exe ml\train.py --config ml\configs\baseline.yaml
.\.venv\Scripts\python.exe ml\train.py --config ml\configs\tuned.yaml
```

## 模型文件已提交进 git

`app/model.joblib`（1.5 MB）**不再被 `.gitignore` 忽略**，随代码一起提交——这样 CI 从 git 检出后构建镜像能直接拿到模型，不需要额外拉取。

代价：每次重训都要提交一个 1.5 MB 的二进制，git 历史会持续增长。等模型体积变大或迭代变频繁时，可以改成 DVC 管理：

```powershell
dvc add app/model.joblib          # 生成 app/model.joblib.dvc
git add app/model.joblib.dvc .gitignore
# CI 里加一步 dvc pull
```

参考 `ml/registry/current_model.md` 的"提升新版本"一节。
