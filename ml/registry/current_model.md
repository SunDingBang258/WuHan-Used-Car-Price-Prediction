# 当前生产模型

> 这份文件是**应用该加载哪个模型**的唯一权威说明。
> 换模型时改这里，不要靠"最后一次训练覆盖了 joblib"来决定。

## 生产版本

| 项目 | 值 |
|---|---|
| 模型 | **`tuned-11feat`**（HistGradientBoostingRegressor） |
| 配置文件 | `ml/configs/tuned.yaml` |
| MLflow run | `5943ec07c33d4b49888d9507cce4de10` |
| 应用文件 | `app/model.joblib`（1,546,617 字节） |
| CV MAPE | **14.12%** |
| CV MAE | 3.00 万元 |
| CV R² | 0.739 |
| 训练数据 | `data/che168_wuhan_cars.csv` md5 `99f0c71c43a3c3a57a4545c74a2bae75` |
| 代码 commit | `61c2fa704c2e13ae503e21e797ab02ffa1b4f819` |
| 定版时间 | 2026-10-18 |

MLflow 页面：

```
https://dagshub.com/q13297638316/WuHan-Used-Car-Price-Prediction.mlflow/#/experiments/1/runs/5943ec07c33d4b49888d9507cce4de10
```

## 为什么是它

- MAPE 14.1%，是对照组 `baseline-8feat`（51.4%）的约 1/3.6
- MAE 3.00 万 vs 基线 7.97 万
- R² 0.739 vs 基线 0.429
- 三个指标同时更好，没有取舍冲突

详细对比和指标取舍见 `ml/README_experiments.md`。

## 输入契约

模型期望 **11 个特征**，顺序即 `features` 列表（存在 `app/model.joblib` 的 payload 里）：

```
品牌ID, 表显里程(万公里), 车龄(年), 年均里程(万公里/年),
0次过户, 原厂质保, 发布时间序号, 准新车标记(站点),
品牌折价率, 车系折价率, 车系中位价
```

后三个是查表特征，由 `app/reference.json` 按（品牌, 车系）查出来：

| 特征 | 来源字段 |
|---|---|
| `品牌折价率` | `reference.json` → `brands[品牌].discount_median` |
| `车系折价率` | `reference.json` → `series[车系].discount_median` |
| `车系中位价` | `reference.json` → `series[车系].price_median` |

`品牌ID` 是**类别特征**（模型构造时用 `categorical_features` 指定了列索引），填字符串数字即可。

## 适用范围

**只对 `app/reference.json` 里覆盖的 30 个品牌 / 279 个车系有效。**

用户输入的车系若不在对照表里，三个查表特征查不到，只能退回全局中位数——早前用按车系分组的交叉验证测过，那种情况下 MAPE 约 55%，基本失去参考价值。

所以应用表单强制从下拉框选品牌/车系，不是限制，是**保证模型在适用范围内工作**。

## 提升新版本

1. 改配置或数据，跑训练：

```powershell
.\.venv\Scripts\python.exe ml\train.py --config ml\configs\tuned.yaml
```

2. 在 MLflow 上对比新旧 run 的 `cv_mape`（同时看 `cv_mae` / `cv_r2` 防止 MAPE 被低价车带偏）

3. **只有在 MAPE 下降且 MAE 没有恶化时**才提升

4. 更新本文件的三处：run id、指标、定版时间

5. 确认 `app/model.joblib` 已被新 run 覆盖（`tuned.yaml` 里 `save_to_app: true`）

6. 提交 `app/model.joblib`（不再被 gitignore 忽略，见 `ml/PROVENANCE.md`）

## 回滚

任一历史 run 的模型都能单独取回：

```powershell
# 下载某个 run 的 joblib
.\.venv\Scripts\python.exe -m mlflow artifacts download `
  --artifact-uri "runs:/<run_id>/model_file/model.joblib" `
  --dst-path app/model.joblib
```

`baseline-8feat` 的 run id 是 `b849f67dbec54312855be07e9d1e105a`（保留它只为对照，**不要**部署）。
