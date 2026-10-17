"""数据访问层: 增删改查 + 名称查表。"""
from __future__ import annotations

import pytest

from app import crud, reference, schemas


def _payload(**overrides):
    data = {
        "brand": "比亚迪",
        "series": "汉",
        "car_age_years": 1.2,
        "mileage_wan": 1.2,
        "zero_transfer": True,
        "factory_warranty": False,
        "near_new": True,
    }
    data.update(overrides)
    return schemas.CarCreate(**data)


def _create(db, **overrides):
    payload = _payload(**overrides)
    return crud.create_car(db, payload, reference.lookup(payload.brand, payload.series))


def test_create_and_get(db_session):
    car = _create(db_session)
    assert car.id is not None
    fetched = crud.get_car(db_session, car.id)
    assert fetched is not None
    assert fetched.series == "汉"
    assert fetched.zero_transfer is True


def test_create_fills_lookup_fields(db_session):
    car = _create(db_session)
    expect = reference.lookup("比亚迪", "汉")
    assert car.brand_id == expect["brand_id"]
    assert car.series_id == expect["series_id"]
    assert float(car.series_price_median) == expect["series_price_median"]


def test_list_and_filter_by_brand(db_session):
    _create(db_session, brand="比亚迪", series="汉")
    _create(db_session, brand="特斯拉", series="Model Y")
    items, total = crud.list_cars(db_session)
    assert total == 2
    assert [c.brand for c in items] == ["特斯拉", "比亚迪"]  # 新的在前
    filtered, n = crud.list_cars(db_session, brand="比亚迪")
    assert n == 1 and filtered[0].brand == "比亚迪"


def test_update_only_touches_given_fields(db_session):
    car = _create(db_session)
    updated = crud.update_car(db_session, car.id, schemas.CarUpdate(mileage_wan=3.5))
    assert float(updated.mileage_wan) == 3.5
    assert updated.brand == "比亚迪"


def test_update_brand_and_series_rewrites_ids(db_session):
    car = _create(db_session, brand="比亚迪", series="汉")
    features = reference.lookup("特斯拉", "Model Y")
    updated = crud.update_car(
        db_session, car.id, schemas.CarUpdate(brand="特斯拉", series="Model Y"), features
    )
    assert updated.series_id == features["series_id"]


def test_delete(db_session):
    car = _create(db_session)
    assert crud.delete_car(db_session, car.id) is True
    assert crud.get_car(db_session, car.id) is None
    assert crud.delete_car(db_session, car.id) is False


def test_series_by_brand_groups_every_brand():
    """联动的数据源: 每个品牌都要有车系列表, 且不含别人的车系。"""
    mapping = reference.series_by_brand()
    assert set(mapping) == set(reference.brand_names())
    assert "Model Y" in mapping["特斯拉"]
    assert "宝马X5" not in mapping["特斯拉"]


def test_lookup_failures():
    with pytest.raises(ValueError, match="不在可选范围"):
        reference.lookup("不存在的品牌", "Model Y")
    with pytest.raises(ValueError, match="不在可选范围"):
        reference.lookup("特斯拉", "不存在的车系")
    with pytest.raises(ValueError, match="不属于"):
        reference.lookup("宝马", "Model Y")
