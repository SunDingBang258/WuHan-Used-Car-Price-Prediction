# 实验记录

所有训练都在 MLflow 上留痕。追踪地址：

```
https://dagshub.com/q13297638316/WuHan-Used-Car-Price-Prediction.mlflow
```

实验名：**`wuhan-used-cars-price`**（2 个 run）

| | 基线 | 调优（生产） |
|---|---|---|
| run 名 | `baseline-8feat` | `tuned-11feat` |
| run id | `b849f67dbec54312855be07e9d1e105a` | `5943ec07c33d4b49888d9507cce4de10` |
| 配置文件 | `configs/baseline.yaml` | `configs/tuned.yaml` |
| 特征数 | 8 | 11 |
| 目标编码特征 | ✗ 不用 | ✓ 用 |
| loss | `squared_error` | `absolute_error` |
| **CV MAPE** | **51.38%** | **14.12%** |
| CV RMSE | 19.78 万 | 13.49 万 |
| CV MAE | 7.97 万 | 3.00 万 |
| CV R² | 0.429 | 0.739 |

复现：

```powershell
.\.venv\Scripts\python.exe ml\train.py --config ml\configs\baseline.yaml
.\.venv\Scripts\python.exe ml\train.py --config ml\configs\tuned.yaml
```

## 生产版本是 `tuned-11feat`

**理由：MAPE 从 51.4% 降到 14.1%，误差降到约 1/3.6。**

两处改动带来了这个差距：

**① 引入三个目标编码特征（主要贡献）**

`品牌折价率` / `车系折价率` / `车系中位价`。其中 `车系中位价` 是决定性特征——用置换法测（把该列打乱后重算 MAPE），它让 MAPE 恶化 **124 个百分点**，远高于其他所有特征。

原因很直接：武汉二手车市场里，**车系一旦确定，价格量级就基本定了**。一辆宝马X5 即便车况一般，也不会卖到宝马3系的价格区间。没有这个信号，模型只能靠"品牌 + 里程 + 车龄"硬猜，误差自然大。

**② `loss` 换成 `absolute_error`**

售价跨度 0.58 万 ~ 588.8 万，跨 3 个数量级。平方误差会被几台豪车主导（一台 588 万的车预测偏 100 万，平方后是 10000，抵得上几百台代步车的误差）。绝对误差对离群值稳健得多，也更贴合"估价"这个场景。

> ⚠️ 这三个特征是**目标编码**——用售价算出来的。交叉验证时必须在**训练折**上重算（`lookup_tables()` 只吃训练折），否则每一行的特征里都含它自己的售价，指标会虚高。这是本脚本最容易踩的坑。

## 优化的指标：MAPE

**主指标是 MAPE（平均绝对百分比误差），不是 RMSE。**

理由：

1. **业务语言对得上**。用户问"这估价准不准"，答案是"一般偏 14%"，而不是"偏 3 万"。3 万对一台 5 万的车是灾难，对一台 300 万的车无感——只有百分比能统一表达。

2. **售价跨 3 个数量级**。RMSE / MAE 会被高价车主导：数据集里一台 588 万的车预测偏 100 万，RMSE 就增加 10000，抵得上几百台代步车的误差。用 RMSE 做选型会得到"为了豪车牺牲所有普通车"的模型。

3. **它和训练目标一致**。`loss="absolute_error"` 优化的就是绝对偏差，MAPE 是其归一化版本，选型指标和优化目标不脱节。

**同时报告 RMSE / MAE / R² 作为交叉验证**，因为 MAPE 有已知缺陷：

- 对**低价车**过分敏感。一台 0.58 万的车上预测偏 0.3 万，MAPE 就是 52%，但它对总误差贡献极小。
- 目标接近 0 时会爆炸（本数据集最低 0.58 万，风险可控）。

所以看板是：**MAPE 为主，MAE 和 R² 为副**。tuned 在这三个上同时更好（14.1% / 3.00 万 / 0.739 vs 51.4% / 7.97 万 / 0.429），不存在指标之间的取舍冲突。

## 已知局限

**冷启动会明显退化。** 应用里用户只能从下拉框选已知车系（`app/reference.json` 里的 279 个），所以只做了随机 5 折——这个划分回答的是"给见过的车系的新车源估价"，贴合实际用法。

但如果拿一个**训练时没见过的车系**来估价，情况差得多：对 `车系中位价`、`车系折价率` 查不到，只能退回全局中位数。早前用 `GroupKFold`（按车系分组，模拟未见车系）测过一次，MAPE 约 **55%**，R² 接近 0。

结论：**这个模型只对对照表覆盖的车系有效**，这正好和表单"必须从下拉框选"的设计吻合。

## 记录了什么

每个 run 都记录了：

| 类别 | 内容 |
|---|---|
| 代码版本 | `git_commit` tag + param（`git rev-parse HEAD`） |
| 数据版本 | `dataset_dvc_hash`（读 `.dvc`）+ `dataset_md5`（实际算），不一致会告警 |
| 超参数 | 配置文件全量 + `n_splits` / `n_features` / `dataset_rows` |
| 指标 | `cv_mape` / `cv_rmse` / `cv_mae` / `cv_r2` / `train_mape` |
| 制品 | `model/`（MLflow LoggedModel）、`model_file/model.joblib`（run 级）、`config/*.yaml`、`cv_folds.json`（逐折指标） |

## 历史说明

DagsHub 上还有一个实验 `wuhan-uesd-cars-price_V1.0.1`，是重构前的单个 run（实验名有拼写错误，`uesd` 应为 `used`）。当前代码统一用 `wuhan-used-cars-price`，旧实验可删。
