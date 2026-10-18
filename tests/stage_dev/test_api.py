"""JSON API: 走真实 HTTP, 覆盖 CRUD 与校验。"""
from __future__ import annotations

from app import reference


def _create(client, sample_payload, **overrides):
    payload = dict(sample_payload)
    payload.update(overrides)
    return client.post("/api/cars", json=payload)


def test_create_fills_lookup_fields(client, sample_payload):
    resp = _create(client, sample_payload)
    assert resp.status_code == 201
    body = resp.json()
    assert body["brand"] == "特斯拉"
    expect = reference.lookup("特斯拉", "Model Y")
    assert body["brand_id"] == expect["brand_id"]
    assert body["series_id"] == expect["series_id"]
    assert body["series_price_median"] == expect["series_price_median"]
    assert body["zero_transfer"] is True and body["near_new"] is False


def test_list_and_filter(client, sample_payload):
    _create(client, sample_payload, brand="特斯拉", series="Model Y")
    _create(client, sample_payload, brand="宝马", series="宝马X5")
    body = client.get("/api/cars").json()
    assert body["total"] == 2
    only = client.get("/api/cars", params={"brand": "宝马"}).json()
    assert only["total"] == 1 and only["items"][0]["brand"] == "宝马"


def test_get_single(client, sample_payload):
    car_id = _create(client, sample_payload).json()["id"]
    assert client.get(f"/api/cars/{car_id}").json()["id"] == car_id
    assert client.get("/api/cars/987654").status_code == 404


def test_put_updates_fields(client, sample_payload):
    car_id = _create(client, sample_payload).json()["id"]
    resp = client.put(f"/api/cars/{car_id}", json={"near_new": True, "mileage_wan": 8.8})
    assert resp.status_code == 200
    body = resp.json()
    assert body["near_new"] is True and body["mileage_wan"] == 8.8
    assert body["brand"] == "特斯拉"


def test_put_brand_and_series_together_recomputes_ids(client, sample_payload):
    car_id = _create(client, sample_payload).json()["id"]
    resp = client.put(f"/api/cars/{car_id}", json={"brand": "宝马", "series": "宝马X5"})
    assert resp.status_code == 200
    assert resp.json()["series_id"] == reference.lookup("宝马", "宝马X5")["series_id"]


def test_put_brand_without_series_rejected(client, sample_payload):
    car_id = _create(client, sample_payload).json()["id"]
    resp = client.put(f"/api/cars/{car_id}", json={"brand": "宝马"})
    assert resp.status_code == 422
    assert "一起改" in resp.text


def test_delete_then_404(client, sample_payload):
    car_id = _create(client, sample_payload).json()["id"]
    assert client.delete(f"/api/cars/{car_id}").status_code == 204
    assert client.get(f"/api/cars/{car_id}").status_code == 404


def test_validation_rejects_bad_input(client, sample_payload):
    assert _create(client, sample_payload, mileage_wan=-1).status_code == 422
    assert _create(client, sample_payload, car_age_years=-1).status_code == 422
    assert _create(client, sample_payload, brand="   ").status_code == 422


def test_unknown_brand_rejected(client, sample_payload):
    resp = _create(client, sample_payload, brand="不存在的品牌")
    assert resp.status_code == 422
    assert "不在可选范围" in resp.text
