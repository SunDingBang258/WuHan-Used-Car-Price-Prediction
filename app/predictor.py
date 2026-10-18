"""加载 app/model.joblib 做价格预测。"""
from __future__ import annotations

from datetime import date
from functools import lru_cache
from pathlib import Path

import joblib
import numpy as np

from app import reference

MODEL_FILE = Path(__file__).with_name("model.joblib")
DATE_ORIGIN = date(2020, 1, 1)


@lru_cache(maxsize=1)
def _payload() -> dict:
    return joblib.load(MODEL_FILE)


def predict(
    *,
    brand: str,
    series: str,
    car_age_years: float,
    mileage_wan: float,
    zero_transfer: bool,
    factory_warranty: bool,
    near_new: bool,
) -> float:
    """返回预估售价(万元)。品牌/车系不在对照表里时抛 ValueError。"""
    payload = _payload()
    info = reference.lookup(brand, series)

    row = {
        # 用户填的
        "表显里程(万公里)": mileage_wan,
        "车龄(年)": car_age_years,
        "年均里程(万公里/年)": mileage_wan / car_age_years if car_age_years else mileage_wan,
        "0次过户": float(zero_transfer),
        "原厂质保": float(factory_warranty),
        "准新车标记(站点)": float(near_new),
        # 挂牌时间按"今天"算, 用户是在当下估价
        "发布时间序号": (date.today() - DATE_ORIGIN).days,
        # 对照表查出来的
        "品牌ID": float(info["brand_id"]),
        "品牌折价率": info["brand_discount_median"],
        "车系折价率": info["series_discount_median"],
        "车系中位价": info["series_price_median"],
    }

    x = np.array([[row[name] for name in payload["features"]]], dtype=float)
    return round(float(payload["model"].predict(x)[0]), 2)
