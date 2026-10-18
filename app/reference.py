"""品牌 / 车系 名称 -> ID 与查表特征。

用户填的是名字, 模型要的是 ID 和几个统计特征 —— 都在这里对上。
查找表 app/reference.json 由 data/export_reference.py 从数据集生成, 随应用一起发布;
数据集更新后重跑那个脚本即可。
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

REFERENCE_FILE = Path(__file__).with_name("reference.json")


@lru_cache(maxsize=1)
def _table() -> dict:
    return json.loads(REFERENCE_FILE.read_text(encoding="utf-8"))


def brand_names() -> list[str]:
    """所有可选品牌名, 给下拉框用。"""
    return list(_table()["brands"])


def series_names() -> list[str]:
    """所有可选车系名, 给下拉框用。"""
    return list(_table()["series"])


def series_by_brand() -> dict[str, list[str]]:
    """{品牌: [该品牌下的车系...]}, 给「选品牌后联动车系」用。"""
    grouped: dict[str, list[str]] = {}
    for name, info in _table()["series"].items():
        grouped.setdefault(info["brand"], []).append(name)
    return grouped


def lookup(brand: str, series: str) -> dict:
    """按名称查出写库要用的字段; 查不到就抛 ValueError。"""
    table = _table()
    brand_info = table["brands"].get(brand)
    if brand_info is None:
        raise ValueError(f"品牌「{brand}」不在可选范围内, 请从下拉框里选")
    series_info = table["series"].get(series)
    if series_info is None:
        raise ValueError(f"车系「{series}」不在可选范围内, 请从下拉框里选")
    if series_info["brand"] != brand:
        raise ValueError(f"车系「{series}」不属于品牌「{brand}」")
    return {
        "brand_id": brand_info["id"],
        "series_id": series_info["id"],
        "brand_discount_median": brand_info["discount_median"],
        "series_discount_median": series_info["discount_median"],
        "series_price_median": series_info["price_median"],
    }
