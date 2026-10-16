"""数据访问层测试: 直接打 crud 函数, 不经过 HTTP。"""
from __future__ import annotations

from app import crud, schemas


def _payload(**overrides):
    data = {
        "brand": "比亚迪",
        "series": "海豹",
        "model_name": "海豹06 DM-i 2025款 智驾版 120KM尊荣型",
        "mileage_wan": 1.2,
        "transfer_times": 0,
        "city": "武汉",
    }
    data.update(overrides)
    return schemas.CarCreate(**data)


def test_create_then_get(db_session):
    car = crud.create_car(db_session, _payload())
    assert car.id is not None
    assert car.created_at is not None and car.updated_at is not None

    fetched = crud.get_car(db_session, car.id)
    assert fetched is not None
    assert fetched.brand == "比亚迪"
    assert fetched.model_name == "海豹06 DM-i 2025款 智驾版 120KM尊荣型"


def test_get_missing_returns_none(db_session):
    assert crud.get_car(db_session, 999999) is None


def test_list_returns_newest_first(db_session):
    first = crud.create_car(db_session, _payload(brand="比亚迪"))
    second = crud.create_car(db_session, _payload(brand="特斯拉"))
    items, total = crud.list_cars(db_session)
    assert total == 2
    assert [c.id for c in items] == [second.id, first.id]


def test_list_filter_by_brand(db_session):
    crud.create_car(db_session, _payload(brand="比亚迪"))
    crud.create_car(db_session, _payload(brand="特斯拉"))
    items, total = crud.list_cars(db_session, brand="比亚迪")
    assert total == 1
    assert items[0].brand == "比亚迪"


def test_list_filter_by_city(db_session):
    crud.create_car(db_session, _payload(city="武汉"))
    crud.create_car(db_session, _payload(city="上海"))
    items, total = crud.list_cars(db_session, city="上海")
    assert total == 1
    assert items[0].city == "上海"


def test_list_pagination(db_session):
    for i in range(5):
        crud.create_car(db_session, _payload(model_name=f"车型 {i}"))
    page1, total = crud.list_cars(db_session, skip=0, limit=2)
    page2, _ = crud.list_cars(db_session, skip=2, limit=2)
    assert total == 5
    assert len(page1) == 2 and len(page2) == 2
    assert {c.id for c in page1}.isdisjoint({c.id for c in page2})


def test_update_only_touches_given_fields(db_session):
    car = crud.create_car(db_session, _payload())
    updated = crud.update_car(db_session, car.id, schemas.CarUpdate(mileage_wan=3.5))
    assert updated is not None
    assert float(updated.mileage_wan) == 3.5
    assert updated.brand == "比亚迪"  # 未传的字段保持原值
    assert updated.city == "武汉"


def test_update_missing_returns_none(db_session):
    assert crud.update_car(db_session, 999999, schemas.CarUpdate(city="上海")) is None


def test_delete(db_session):
    car = crud.create_car(db_session, _payload())
    assert crud.delete_car(db_session, car.id) is True
    assert crud.get_car(db_session, car.id) is None
    assert crud.delete_car(db_session, car.id) is False
