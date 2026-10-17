"""训练二手车价格预测模型, 全程用 MLflow 记录。

用法
----
    .\\.venv\\Scripts\\python.exe ml/train.py                          # 默认 configs/tuned.yaml
    .\\.venv\\Scripts\\python.exe ml/train.py --config ml/configs/baseline.yaml

每次运行会记录:
    代码版本   git commit SHA             -> tag
    数据版本   DVC 哈希 + 实际 md5        -> param
    超参数     configs/*.yaml 的内容      -> param
    指标       5 折 CV 的 MAPE / MAE / R² -> metric
    制品       模型(log_model) + config 副本 + 逐折指标表 -> artifact

输入: data/che168_wuhan_cars.csv (DVC 管理)
产出: MLflow run; 当 config 里 save_to_app: true 时再写 app/model.joblib

关键设计
--------
1. 品牌折价率 / 车系折价率 / 车系中位价 是用**售价**算出来的(目标编码)。交叉验证必须在
   训练折上重算, 否则每一行的特征里都含自己那一行的售价, 指标会虚高。
2. 用户只能从下拉框选已知车系, 所以只做随机 5 折, 不做"没见过车系"的冷启动评估。
3. 车系ID 有 279 个取值, 超过 HistGradientBoosting 对类别特征的 255 上限, 所以不当类别用,
   它的身份由「车系折价率」「车系中位价」承载。
"""
from __future__ import annotations

import argparse
import hashlib
import os
import re
import subprocess
import tempfile
from pathlib import Path

import joblib
import mlflow
import numpy as np
import pandas as pd
import sklearn
import yaml
from dotenv import load_dotenv
from mlflow.models import infer_signature
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.metrics import mean_absolute_error, mean_absolute_percentage_error, r2_score
from sklearn.model_selection import KFold

ROOT = Path(__file__).resolve().parent.parent
CSV = ROOT / "data" / "che168_wuhan_cars.csv"
DVC_FILE = ROOT / "data" / "che168_wuhan_cars.csv.dvc"
MODEL_OUT = ROOT / "app" / "model.joblib"
DEFAULT_CONFIG = Path(__file__).parent / "configs" / "tuned.yaml"

TARGET = "售价(万元)"
GUIDE = "新车指导价(万元)"

CATEGORICAL = ["品牌ID"]
PLAIN = [
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

# 顺序有讲究: dagshub 在 import 的那一刻就会去读凭据, 所以 .env 必须先载入环境变量,
# 否则即使 DAGSHUB_USER_TOKEN 写在 .env 里, dagshub.init() 也会退化成弹浏览器授权。
load_dotenv(ROOT / ".env")

MLFLOW_DB = ROOT / "mlflow.db"  # 本地兜底: 整个 MLflow 库就是这一个文件
if os.getenv("DAGSHUB_USER_TOKEN"):
    import dagshub

    dagshub.init(
        repo_owner="q13297638316",
        repo_name="WuHan-Used-Car-Price-Prediction",
        mlflow=True,
    )
else:
    mlflow.set_tracking_uri(f"sqlite:///{MLFLOW_DB.as_posix()}")
    print(f"未设置 DAGSHUB_USER_TOKEN, MLflow 记录到本地 {MLFLOW_DB.name}")

mlflow.set_experiment("wuhan-used-cars-price")


# ---------------------------------------------------------------- 版本信息
def git_commit() -> str:
    """当前 HEAD 的 commit SHA; 拿不到就返回 unknown。"""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT, capture_output=True, text=True, timeout=10, check=True,
        )
        return out.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def dataset_version() -> dict:
    """DVC 记录的哈希 + 实际算出来的 md5, 两者不一致说明 dvc add 忘了跑。"""
    actual = hashlib.md5(CSV.read_bytes()).hexdigest()
    recorded = ""
    if DVC_FILE.exists():
        match = re.search(r"md5:\s*(\S+)", DVC_FILE.read_text(encoding="utf-8"))
        recorded = match.group(1) if match else ""
    return {"dvc_hash": recorded or "unknown", "actual_md5": actual, "in_sync": recorded == actual}


# ---------------------------------------------------------------- 数据
def load_config(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def load_data() -> pd.DataFrame:
    df = pd.read_csv(CSV, header=2, skip_blank_lines=True)
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
    return CATEGORICAL + PLAIN + ([name for _c, name in LOOKUP_KEYS] if use_lookups else [])


def build_x(
    frame: pd.DataFrame, use_lookups: bool,
    tables: dict | None = None, fallback: dict | None = None,
) -> pd.DataFrame:
    """拼特征矩阵, 列名即 feature_names()。不用查表特征时就只拼原始列。"""
    columns = [frame[CATEGORICAL + PLAIN].to_numpy(dtype=float)]
    names = CATEGORICAL + PLAIN
    if use_lookups:
        columns.append(np.column_stack([
            frame[col].map(tables[key]).fillna(fallback[key]).to_numpy()
            for col, key in LOOKUP_KEYS
        ]))
        names = names + [name for _c, name in LOOKUP_KEYS]
    return pd.DataFrame(np.column_stack(columns), columns=names)


def make_model(cfg: dict, names: list[str]) -> HistGradientBoostingRegressor:
    return HistGradientBoostingRegressor(
        loss=cfg.get("loss", "squared_error"),
        learning_rate=cfg.get("learning_rate", 0.1),
        max_iter=cfg.get("max_iter", 100),
        max_leaf_nodes=cfg.get("max_leaf_nodes", 31),
        min_samples_leaf=cfg.get("min_samples_leaf", 20),
        l2_regularization=cfg.get("l2_regularization", 0.0),
        categorical_features=[names.index(c) for c in CATEGORICAL],
        random_state=SEED,
    )


# ---------------------------------------------------------------- 训练
def cross_validate(df: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    use_lookups = bool(cfg.get("use_lookups", False))
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
            "RMSE": float(np.sqrt(np.mean((true - pred) ** 2))),
            "MAE": mean_absolute_error(true, pred),
            "R2": r2_score(true, pred),
        })
    return pd.DataFrame(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description="训练价格预测模型并记录到 MLflow")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG, help="训练配置 yaml")
    args = parser.parse_args()

    cfg = load_config(args.config)
    use_lookups = bool(cfg.get("use_lookups", False))
    names = feature_names(use_lookups)

    df = load_data()
    ver = dataset_version()
    sha = git_commit()

    print(f"配置: {args.config.name}  ({cfg.get('name')})")
    print(f"  特征 {len(names)} 个, use_lookups={use_lookups}")
    print(f"  数据 {len(df)} 条   代码 {sha[:12]}   数据 {ver['actual_md5'][:12]}")
    if not ver["in_sync"]:
        print(f"  [!] DVC 哈希和实际文件不一致: 记录 {ver['dvc_hash']} != 实际 {ver['actual_md5']}")

    cv = cross_validate(df, cfg)
    print(f"\n=== 随机 {N_SPLITS} 折 ===")
    for _, r in cv.iterrows():
        print(f"  折 {int(r['fold'])}:  MAPE {r['MAPE']:5.1f}%   RMSE {r['RMSE']:6.2f} 万   "
              f"MAE {r['MAE']:6.2f} 万   R² {r['R2']:.3f}")
    print(f"  均值:  MAPE {cv['MAPE'].mean():5.1f}%   RMSE {cv['RMSE'].mean():6.2f} 万   "
          f"MAE {cv['MAE'].mean():6.2f} 万   R² {cv['R2'].mean():.3f}")

    # 全量训练最终模型
    tables, fallback = lookup_tables(df) if use_lookups else (None, None)
    x = build_x(df, use_lookups, tables, fallback)
    y = df[TARGET].to_numpy()
    model = make_model(cfg, names)
    model.fit(x, y)

    with mlflow.start_run(run_name=f"{cfg.get('name')}-{len(names)}feat"):
        # 代码版本 / 数据版本
        mlflow.set_tag("git_commit", sha)
        mlflow.set_tag("config_name", str(cfg.get("name")))
        mlflow.set_tag("use_lookups", str(use_lookups))
        mlflow.log_params({
            "git_commit": sha[:12],
            "dataset_dvc_hash": ver["dvc_hash"],
            "dataset_md5": ver["actual_md5"],
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

        # 制品: 模型 + 逐折指标表 + 配置副本
        signature = infer_signature(x, model.predict(x))
        mlflow.sklearn.log_model(
            sk_model=model,
            name="model",
            signature=signature,
            input_example=x.head(3),
            # MLflow 默认的 skops 会拒绝 HistGradientBoosting(内部 TreePredictor 被判为
            # 不可信类型); 模型是我们自己训的, cloudpickle 足够且不受 sklearn 内部改名影响
            serialization_format="cloudpickle",
            pip_requirements=[
                f"scikit-learn=={sklearn.__version__}",
                f"pandas=={pd.__version__}",
                f"numpy=={np.__version__}",
            ],
        )
        mlflow.log_table(data=cv, artifact_file="cv_folds.json")
        mlflow.log_artifact(str(args.config), artifact_path="config")

        # 除了上面那个 LoggedModel(MLflow 3 把模型存成独立实体), 再存一份 joblib 作为
        # run 级制品 —— 这样 run 的 Artifacts 页里能直接点开模型文件。
        with tempfile.TemporaryDirectory() as tmp:
            dump = Path(tmp) / "model.joblib"
            joblib.dump({"model": model, "features": names}, dump)
            mlflow.log_artifact(str(dump), artifact_path="model_file")

        run_id = mlflow.active_run().info.run_id
        print(f"\nMLflow run: {run_id}")

    if cfg.get("save_to_app"):
        payload = {
            "model": model,
            "features": names,
            "categorical": CATEGORICAL,
            "target": TARGET,
            "trained_rows": len(df),
            "run_id": run_id,
            "git_commit": sha,
            "dataset_md5": ver["actual_md5"],
        }
        MODEL_OUT.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(payload, MODEL_OUT)
        print(f"已保存 {MODEL_OUT.relative_to(ROOT)} ({MODEL_OUT.stat().st_size:,} 字节)")
    else:
        print("config 里 save_to_app=false, 不覆盖 app/model.joblib")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
