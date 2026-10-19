# 溯源（Provenance）

从爬虫到线上模型的完整链条，以及每一步的版本怎么定位。

## 链路

```
① 爬虫           ⚠️ 已丢失: 原本是 data/爬虫/che168_crawler.py --brand-pages N
                  (品牌清单在 TARGET_BRANDS, 30 个)
                  这个目录被 data/.gitignore 忽略、也没纳入 DVC, 现在本地已不存在,
                  所以「从原始抓取重新生成数据集」这一步目前无法复现
                  (详见 README_pipeline.md §13.6)
                           ↓
② 原始数据       data/爬虫/che168_wuhan_brands.csv          3222 条, 19 列   ⚠️ 已丢失
                 data/数据处理/che168_wuhan_cars.raw.csv    2239 条, 31 列   ✓ 还在
                           ↓
③ 数据流水线     ml/data_pipeline.py
                 · 合并去重（A 优先）
                 · 丢空 / 丢矛盾值
                 · 补派生列（车系名称 / 年均里程）
                 · 组过滤（v2 才做）
                 · 补目标编码（⚠️ 必须在组过滤之后）
                           ↓
④ 训练数据集     data/che168_wuhan_cars.csv    3141 条, 20 列   ← DVC 管理
                 data/che168_wuhan_cars.csv.dvc
                          ↓
⑤ 对照表         app/reference.json            30 品牌 / 279 车系
                 （同一条命令产出，应用运行时读）
                          ↓
⑥ 训练           python ml/train.py   (配置在 train.py 顶部)
                          ↓
⑦ 模型记录       MLflow run  +  LoggedModel     ← DagsHub
                          ↓
⑧ 应用加载       app/model.joblib              1,545,145 字节
```

## 当前生产版本的全部版本号

| 项目 | 值 |
|---|---|
| 代码 commit | `f092717bf57cb1adc3b07f6217f1d19563c76218`（存在 `app/model.joblib` 的 `git_commit` 里） |
| 数据集 DVC hash = 实际 md5 | `4439910deb63db4bc4ec0646389c1962` |
| 数据集行数 / 字节 | 3141 / 793,525 |
| 配置 | `ml/train.py` 顶部 `CONFIG = TUNED` |
| MLflow run id | `33261395cea44946b226665d77b08e10` |
| MLflow LoggedModel | `m-7373d984c70b4584a418c1bcefc33e12` |
| 应用模型文件 | `app/model.joblib`（1,545,145 字节） |
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
with csv.open("rb") as fh:                              # 实际文件的 md5
    actual = hashlib.file_digest(fh, "md5").hexdigest()
recorded = re.search(r"md5:\s*(\S+)", dvc_file)         # .dvc 里记的
```

两者都会作为 param 记录（`dataset_md5` / `dataset_dvc_hash`）。**不一致时脚本会打印告警**——意思是 `dvc add` 忘了跑，`.dvc` 文件已过期。

**超参数** —— 配置全部进 param，同时把配置快照作为 artifact 存一份（`files/config.json`），这样即使以后配置改了也能还原当次的确切参数。

**指标** —— 5 折 CV 的均值进 metric，逐折明细作为 artifact（`cv_folds.json`）。

**制品** —— 三层都留了：

| 位置 | 内容 |
|---|---|
| `model/`（LoggedModel） | MLflow 3 的模型实体，带 signature、input_example、requirements |
| `files/model.joblib` | run 级制品，直接可下载 |
| `app/model.joblib` | 应用实际加载的，当 `save_to_app: True` 时写入 |

## 复现方式

```powershell
# 0) 训练依赖 —— 和跑服务的依赖分开, 别混用
#    (requirements-ml.txt 里有 mlflow / dagshub, 会让安装集从 36 个包涨到 121 个)
pip install -r requirements-ml.txt

# 1) 数据集（从原始爬取重建，会覆盖 data/che168_wuhan_cars.csv）
#    ⚠️ 需要 data/爬虫/che168_wuhan_brands.csv, 而它已经丢失, 所以这一步目前会报
#    FileNotFoundError。只想拿到数据请用下面的 dvc pull。
.\.venv\Scripts\python.exe ml\data_pipeline.py

# 2) 从 DVC 拉回数据集（推荐, 不需要原始爬虫数据）
dvc pull

# 3) 训练。超参和数据集路径都在 ml/train.py 顶部的「配置区」, 改 CONFIG 常量切换基线/调优
.\.venv\Scripts\python.exe ml\train.py   # 先改成 CONFIG = BASELINE
.\.venv\Scripts\python.exe ml\train.py   # 用 CONFIG = TUNED
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
