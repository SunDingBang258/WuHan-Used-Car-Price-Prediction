"""训练二手车价格预测模型, 全程用 MLflow 记录。

用法
----
要换数据集或超参, 改下面「配置区」里的常量即可:
    DATASET  选 v1 还是 v2
    CONFIG   选 BASELINE 还是 TUNED

每次运行会记录:
    代码版本   git commit SHA             -> tag
    数据版本   DVC 哈希 + 实际 md5        -> param
    超参数     CONFIG 里的全部键          -> param + config.json 制品
    指标       5 折 CV 的 MAPE / MAE / R² -> metric
    制品       模型(log_model) + config.json + 逐折指标表

产出: MLflow run; 当 CONFIG 里 save_to_app 为 True 时再写 app/model.joblib

关键设计
--------
1. 品牌折价率 / 车系折价率 / 车系中位价 是用**售价**算出来的(目标编码)。交叉验证必须在
   训练折上重算, 否则每一行的特征里都含自己那一行的售价, 指标会虚高。
2. 用户只能从下拉框选已知车系, 所以只做随机 5 折, 不做"没见过车系"的冷启动评估。
3. 车系ID 有 279 个取值, 超过 HistGradientBoosting 对类别特征的 255 上限, 所以不当类别用,
   它的身份由「车系折价率」「车系中位价」承载。
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import tempfile
from pathlib import Path

import joblib
import mlflow
import numpy as np
import pandas as pd
import sklearn
from dotenv import load_dotenv
from mlflow.models import ModelSignature
from mlflow.types.schema import ColSpec, Schema
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.metrics import (
    mean_absolute_error,
    mean_absolute_percentage_error,
    r2_score,
    root_mean_squared_error,
)
from sklearn.model_selection import KFold

ROOT = Path(__file__).resolve().parent.parent
MODEL_OUT = ROOT / "app" / "model.joblib"

# ============================== 配置区(直接改这里) ==============================

# 数据集路径, 相对仓库根。项目里有两个 DVC 版本:
#   v1  data/che168_wuhan_cars_v1.csv   3408 条, 未做车系归一化 / 未做组过滤
#   v2  data/che168_wuhan_cars.csv      3141 条, 车系名一一对应 + 组过滤后的最终版
DATASET = "data/che168_wuhan_cars.csv"  # ← 想换 v1 就改成 data/che168_wuhan_cars_v1.csv

# 对照组: sklearn 默认超参, 并且不用任何目标编码特征(折价率/车系中位价)
BASELINE = {
    "name": "baseline",
    "description": "HistGradientBoosting 默认超参, 只用原始特征(不含折价率/车系中位价)",
    "use_lookups": False,       # 关键差异: 不启用目标编码特征
    "loss": "squared_error",
    "learning_rate": 0.1,
    "max_iter": 100,
    "max_leaf_nodes": 31,
    "min_samples_leaf": 20,
    "l2_regularization": 0.0,
    "save_to_app": False,       # 不覆盖 app/model.joblib
}

# 生产版: 加入三个目标编码特征, loss 换成绝对误差, 并调了学习率与树规模
TUNED = {
    "name": "tuned",
    "description": "加入品牌/车系折价率与车系中位价, loss=absolute_error, 调整学习率与树规模",
    "use_lookups": True,
    "loss": "absolute_error",
    "learning_rate": 0.06,
    "max_iter": 400,
    "max_leaf_nodes": 31,
    "min_samples_leaf": 20,
    "l2_regularization": 1.0,
    "save_to_app": True,        # 训练完覆盖 app/model.joblib, 供应用推理
}

# ← 改这一行切换要训哪个: CONFIG = BASELINE  或  CONFIG = TUNED
CONFIG = TUNED

# ================================================================================

TARGET = "售价(万元)"
GUIDE = "新车指导价(万元)"

CATEGORICAL = ["品牌ID"]
NUMERIC = [
    "表显里程(万公里)",
    "车龄(年)",
    "年均里程(万公里/年)",
    "0次过户",
    "原厂质保",
    "发布时间序号",
    "准新车标记(站点)",
]
LOOKUP_KEYS = [
    ("品牌ID", "品牌折价率"),
    ("车系ID", "车系折价率"),
    ("车系ID", "车系中位价"),
]

N_SPLITS = 5
SEED = 42
DATE_ORIGIN = pd.Timestamp("2020-01-01")


# ---------------------------------------------------------------- 实验跟踪
def setup_mlflow() -> None:
    """把 MLflow 指向 DagsHub 的 wuhan-used-cars-price 实验。

    顺序有讲究: dagshub 在 import 的那一刻就去读凭据, 所以 .env 必须先载入环境变量,
    否则即使 DAGSHUB_USER_TOKEN 写在 .env 里, dagshub.init() 也会退化成弹浏览器授权。
    实验记录只走 DagsHub, 不做本地兜底 —— 少了 token 就直接报错, 不悄悄写本地。
    """
    load_dotenv(ROOT / ".env")

    import dagshub

    dagshub.init(
        repo_owner="q13297638316",
        repo_name="WuHan-Used-Car-Price-Prediction",
        mlflow=True,
    )
    mlflow.set_experiment("wuhan-used-cars-price")


# ---------------------------------------------------------------- 版本信息
def git_commit() -> str:
    """当前 HEAD 的 commit SHA。"""
    out = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True
    )
    return out.stdout.strip() or "unknown"


def dataset_version(csv: Path) -> dict:
    """DVC 记录的哈希 + 实际算出来的 md5, 两者不一致说明 dvc add 忘了跑。"""
    dvc_file = csv.parent / (csv.name + ".dvc")
    with csv.open("rb") as fh:
        actual = hashlib.file_digest(fh, "md5").hexdigest()
    recorded = ""
    if dvc_file.exists():
        match = re.search(r"md5:\s*(\S+)", dvc_file.read_text(encoding="utf-8"))
        recorded = match.group(1) if match else ""
    return {
        "dvc_hash": recorded or "unknown",
        "actual_md5": actual,
        "in_sync": recorded == actual, #判断是否相等
    }


# ---------------------------------------------------------------- 数据
def load_data(csv: Path) -> pd.DataFrame:
    # CSV 前两行是标题行和维度行, 第 3 行才是真正的列名, 所以 header=2
    df = pd.read_csv(csv, header=2, skip_blank_lines=True)
    df = df[df[TARGET].notna()].copy()
    for col in CATEGORICAL:
        df[col] = df[col].astype(str)
    df["发布时间序号"] = (pd.to_datetime(df["发布时间"]) - DATE_ORIGIN).dt.days
    for col in ("0次过户", "原厂质保", "准新车标记(站点)"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def lookup_tables(train: pd.DataFrame) -> tuple[dict[str, pd.Series], dict]:
    """只用训练折算三张查表(目标编码), 同时给出没见过的组的兜底值。"""
    ratio = (train[GUIDE] - train[TARGET]) / train[GUIDE] * 100.0
    tables = {
        "品牌折价率": ratio.groupby(train["品牌ID"]).median(),
        "车系折价率": ratio.groupby(train["车系ID"]).median(),
        "车系中位价": train[TARGET].groupby(train["车系ID"]).median(),
    }
    fallback = {
        "品牌折价率": float(ratio.median()),
        "车系折价率": float(ratio.median()),
        "车系中位价": float(train[TARGET].median()),
    }
    return tables, fallback


def feature_names(use_lookups: bool) -> list[str]:
    """模型输入列名, 顺序就是特征矩阵的列顺序。"""
    return CATEGORICAL + NUMERIC + ([name for _c, name in LOOKUP_KEYS] if use_lookups else [])


def build_x (
    frame: pd.DataFrame, use_lookups: bool,
    tables: dict | None = None, fallback: dict | None = None,
) -> np.ndarray:
    """拼特征矩阵, 列的顺序就是 feature_names()。

    不用 DataFrame 是刻意的: 用 DataFrame 训练会让 sklearn 记住 feature_names_in_,
    之后应用里用 ndarray 推理就会警告 "X does not have valid feature names"。
    列名由下面手工构造的 ModelSignature 提供, 效果一样。

    品牌ID / 车系ID 在 CSV 里是数字字符串, 这里统一转成 float 交给模型。
    """
    columns = [frame[CATEGORICAL + NUMERIC].to_numpy(dtype=float)]
    if use_lookups:
        columns.append(np.column_stack([
            frame[col].map(tables[key]).fillna(fallback[key]).to_numpy()
            for col, key in LOOKUP_KEYS
        ]))
    return np.column_stack(columns)


def make_model(cfg: dict, names: list[str]) -> HistGradientBoostingRegressor:
    """按配置建模型; categorical_features 要的是列下标, 不是列名。"""
    return HistGradientBoostingRegressor(
        loss=cfg["loss"],
        learning_rate=cfg["learning_rate"],
        max_iter=cfg["max_iter"],
        max_leaf_nodes=cfg["max_leaf_nodes"],
        min_samples_leaf=cfg["min_samples_leaf"],
        l2_regularization=cfg["l2_regularization"],
        categorical_features=[names.index(col) for col in CATEGORICAL],
        random_state=SEED,
    )


# ---------------------------------------------------------------- 训练
def cross_validate(df: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    """5 折交叉验证。目标编码特征在每一折内只用训练部分重算, 防止目标泄漏。"""
    use_lookups = cfg["use_lookups"]
    names = feature_names(use_lookups)
    rows = []

    for fold, (train_idx, test_idx) in enumerate(
        KFold(N_SPLITS, shuffle=True, random_state=SEED).split(df), start=1
    ):
        train_df, test_df = df.iloc[train_idx], df.iloc[test_idx]
        tables, fallback = lookup_tables(train_df) if use_lookups else (None, None)

        model = make_model(cfg, names)
        model.fit(
            build_x(train_df, use_lookups, tables, fallback),
            train_df[TARGET].to_numpy(),
        )
        pred = model.predict(build_x(test_df, use_lookups, tables, fallback))
        true = test_df[TARGET].to_numpy()

        rows.append({
            "fold": fold,
            "n_test": len(test_idx),
            "MAPE": mean_absolute_percentage_error(true, pred) * 100,
            "RMSE": root_mean_squared_error(true, pred),
            "MAE": mean_absolute_error(true, pred),
            "R2": r2_score(true, pred),
        })
    return pd.DataFrame(rows)


def log_run_artifacts(cfg: dict, model, names: list[str]) -> None:
    """run 级制品: 配置快照 + 可直接下载的 joblib。"""
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "config.json").write_text(
            json.dumps({"dataset": DATASET, **cfg}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        joblib.dump({"model": model, "features": names}, Path(tmp) / "model.joblib")
        mlflow.log_artifacts(tmp, artifact_path="files")


def main() -> int:
    setup_mlflow()

    cfg = CONFIG
    use_lookups = cfg["use_lookups"]
    names = feature_names(use_lookups)
    csv = ROOT / DATASET

    df = load_data(csv)
    ver = dataset_version(csv)
    sha = git_commit()

    print(f"配置 {cfg['name']}: {cfg['description']}")
    print(f"  数据集 {DATASET}  {len(df)} 条   特征 {len(names)} 个 (use_lookups={use_lookups})")
    print(f"  代码 {sha[:12]}   数据 md5 {ver['actual_md5'][:12]}")
    if not ver["in_sync"]:
        print(f"  [!] DVC 哈希与实际文件不一致: {ver['dvc_hash']} != {ver['actual_md5']}")

    cv = cross_validate(df, cfg)
    print(f"\n=== {N_SPLITS} 折交叉验证 ===")
    for _, r in cv.iterrows():
        print(f"  折 {int(r['fold'])}: MAPE {r['MAPE']:5.1f}%  RMSE {r['RMSE']:6.2f}  "
              f"MAE {r['MAE']:6.2f}  R² {r['R2']:.3f}")
    print(f"  均值: MAPE {cv['MAPE'].mean():5.1f}%  RMSE {cv['RMSE'].mean():6.2f}  "
          f"MAE {cv['MAE'].mean():6.2f}  R² {cv['R2'].mean():.3f}")

    # 用全量数据训练最终模型
    tables, fallback = lookup_tables(df) if use_lookups else (None, None)
    x = build_x(df, use_lookups, tables, fallback)
    y = df[TARGET].to_numpy()
    model = make_model(cfg, names).fit(x, y)

    with mlflow.start_run(run_name=f"{cfg['name']}-{len(names)}feat"):
        # 课程要求记录的四项: 代码版本 / 数据版本 / 超参 / 指标 (+ 制品)
        mlflow.set_tags({
            "git_commit": sha,
            "config_name": cfg["name"],
            "use_lookups": str(use_lookups),
        })
        mlflow.log_params({
            "git_commit": sha[:12],
            "dataset": DATASET,
            "dataset_md5": ver["actual_md5"],
            "dataset_dvc_hash": ver["dvc_hash"],
            "dataset_rows": len(df),
            "n_features": len(names),
            "n_splits": N_SPLITS,
            **{k: v for k, v in cfg.items() if k != "description"},
        })
        mlflow.log_metrics({
            "cv_mape": cv["MAPE"].mean(),
            "cv_rmse": cv["RMSE"].mean(),
            "cv_mae": cv["MAE"].mean(),
            "cv_r2": cv["R2"].mean(),
            "train_mape": mean_absolute_percentage_error(y, model.predict(x)) * 100,
        })

        # signature 手工构造: 训练输入是 ndarray(见 build_x), infer_signature 拿不到列名
        mlflow.sklearn.log_model(
            sk_model=model,
            name="model",
            serialization_format="cloudpickle",  # skops 会拒绝 HistGradientBoosting 的内部类型
            signature=ModelSignature(
                inputs=Schema([ColSpec("double", n) for n in names]),
                outputs=Schema([ColSpec("double", "price_wan")]),
            ),
            input_example={n: float(v) for n, v in zip(names, x[0], strict=True)},
            pip_requirements=[
                f"scikit-learn=={sklearn.__version__}",
                f"numpy=={np.__version__}",
            ],
        )
        mlflow.log_table(data=cv, artifact_file="cv_folds.json")
        log_run_artifacts(cfg, model, names)

        run_id = mlflow.active_run().info.run_id
        print(f"\nMLflow run: {run_id}")

    if not cfg["save_to_app"]:
        print(f"{cfg['name']} 的 save_to_app=False, 不覆盖 app/model.joblib")
        return 0

    MODEL_OUT.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump({
        "model": model,
        "features": names,
        "categorical": CATEGORICAL,
        "target": TARGET,
        "trained_rows": len(df),
        "run_id": run_id,
        "git_commit": sha,
        "dataset_md5": ver["actual_md5"],
    }, MODEL_OUT)
    print(f"已保存 {MODEL_OUT.relative_to(ROOT)} ({MODEL_OUT.stat().st_size:,} 字节)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
