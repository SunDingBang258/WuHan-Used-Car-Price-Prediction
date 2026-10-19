# 实验记录

所有训练都在 MLflow 上留痕。追踪地址：

```
https://dagshub.com/q13297638316/WuHan-Used-Car-Price-Prediction.mlflow
```

实验名：**`wuhan-used-cars-price`**（2 个 run）

## 两个实验的对比

| | 基线 | 调优（生产） |
|---|---|---|
| run 名 | `baseline-8feat` | `tuned-11feat` |
| run id | `f9c5532b8d6845d7b78c5a0c7a427387` | `33261395cea44946b226665d77b08e10` |
| 配置 | `ml/configs/baseline.yaml` | `ml/configs/tuned.yaml` |
| 特征数 | 8 | 11 |
| 目标编码特征 | ✗ 不用 | ✓ 用 |
| loss | `squared_error` | `absolute_error` |
| **CV MAPE** | **51.38%** | **14.12%** |
| CV RMSE | 19.78 万 | 13.49 万 |
| CV MAE | 7.97 万 | 3.00 万 |
| CV R² | 0.429 | 0.739 |

复现（超参和数据集路径都在 `ml/configs/*.yaml`，改 `train.py` 顶部的 `CONFIG_PATH` 切换）：

```powershell
.\.venv\Scripts\python.exe ml\train.py   # 先把 CONFIG_PATH 指向 configs/baseline.yaml
.\.venv\Scripts\python.exe ml\train.py   # 再指回 configs/tuned.yaml(默认)
```

---

## 生产版本是 `tuned-11feat`

**理由：MAPE 从 51.4% 降到 14.1%，平均每台车估错 3.00 万。**

### 逐步消融：每个改动贡献了多少

从全默认配置出发，一次只改一处，每步都跑测试：

| 步骤 | 特征 | MAPE | RMSE | MAE | R² | 边际贡献 |
|---|---|---|---|---|---|---|
| 1. baseline（全默认） | 8 | 51.4% | 19.78 | 7.97 | 0.429 | — |
| 2. **+ 三个目标编码特征** | 11 | **17.3%** | 12.76 | 3.40 | 0.765 | **−34.1 pp** |
| 3. **+ `loss=absolute_error`** | 11 | **14.8%** | 13.83 | 3.15 | 0.727 | **−2.5 pp** |
| 4. **+ `lr=0.06` / `iter=400`** | 11 | **14.3%** | 13.48 | 3.00 | 0.740 | **−0.5 pp** |
| 5. **+ `l2_regularization=1.0`**（= tuned） | 11 | **14.1%** | 13.49 | 3.00 | 0.739 | **−0.2 pp** |

特征工程的提升是最大的

### 为什么 `loss` 换成 `absolute_error`

售价跨度 **0.58 万 ~ 588.8 万，跨 3 个数量级**。

举个数：一台 588 万的车预测偏 100 万，误差平方是 **10000 万²**；
一台 5 万的车预测偏 0.5 万，误差平方是 **0.25 万²** —— 前者是后者的 **40000 倍**。
用 MSE 训练，模型会为了那一台豪车牺牲掉几万台代步车的准确度。

绝对误差对离群值稳健得多，也更贴合"估价"这个场景。

---

## 优化的指标：MAPE

**主指标是 MAPE（平均绝对百分比误差），不是 RMSE。**

$$\text{MAPE} = \frac{1}{n}\sum \left| \frac{\hat{y} - y}{y} \right| \times 100\%$$

三条理由：

1. **业务上关心相对误差**。"估高了 10%"比"估高了 3 万"更能说明问题 ——
   同样偏 3 万，对 20 万的车是 15%，对 200 万的车只有 1.5%。
2. **不受价格量级影响**。数据集里 0.58 万和 588.8 万的车混在一起，
   用 MAE 会被贵车主导，用 MAPE 每台车权重相同。
3. **和训练目标对齐**。`loss="absolute_error"` 优化的就是绝对偏差，
   MAPE 是它的归一化版本，选型指标和优化目标不脱节。

**同时报告 RMSE / MAE / R² 作为交叉验证**，因为 MAPE 有已知缺陷：

- 对**低价车**过分敏感。一台 0.58 万的车上预测偏 0.3 万，MAPE 就是 52%，
  但它对总误差贡献极小。
- 目标接近 0 时会爆炸（本数据集最低 0.58 万，风险可控）。

所以看板是：**MAPE 为主，MAE 和 R² 为副**。tuned 在这三个上同时更好
（14.1% / 3.00 万 / 0.739 vs 51.4% / 7.97 万 / 0.429），不存在指标之间的取舍冲突。

---

## 每次训练记录了哪些信息

| 类别 | 内容 |
|---|---|
| 代码版本 | `git_commit` tag + param（`git rev-parse HEAD`） |
| 数据版本 | `dataset`（路径）+ `dataset_dvc_hash`（读 `.dvc`）+ `dataset_md5`（实际算），不一致会告警 |
| 超参数 | `CONFIG` 里的全部键 + `n_splits` / `n_features` / `dataset_rows` |
| 指标 | `cv_mape` / `cv_rmse` / `cv_mae` / `cv_r2` / `train_mape` |
| 制品 | `model/`（MLflow LoggedModel）、`files/model.joblib`（run 级）、`files/config.json`、`cv_folds.json`（逐折指标） |

## 参数是怎么定的

**没有做网格搜索** —— `baseline.yaml` 的 6 个参数就是 sklearn 的原样默认值 ✓
`tuned.yaml` 只改了 4 个，每个都有明确的理由：

| 参数 | baseline | tuned | 理由 |
|---|---|---|---|
| `loss` | `squared_error` | `absolute_error` | 目标跨 1000 倍 + 主指标是相对误差 |
| `learning_rate` | `0.1` | `0.06` | 与 `max_iter` 配合（学习率 × 迭代 ≈ 常数）|
| `max_iter` | `100` | `400` | 同上，小步走更远 |
| `l2_regularization` | `0.0` | `1.0` | 279 个车系 / 3141 行，平均每系 11 条，防过拟合 |
| `max_leaf_nodes` | `31` | `31` | **没改** |
| `min_samples_leaf` | `20` | `20` | **没改**，默认值已是"一叶至少 20 条"的保护 |

上文的消融实验已经验证：这 4 处改动的总收益是 **2.9 个百分点**（14.1% vs 17.3%），
远比特征工程（34.1 个百分点）小。**想再提升应该去搞数据和特征，而不是调参。**
