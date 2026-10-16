"""JSON API 测试: 走真实 HTTP 层(TestClient), 覆盖 CRUD 与校验。"""
from __future__ import annotations


def _create(client, sample_payload, **overrides):
    payload = dict(sample_payload)
    payload.update(overrides)
    return client.post("/api/cars", json=payload)


def test_create_returns_201_and_body(client, sample_payload):
    resp = _create(client, sample_payload)
    assert resp.status_code == 201
    body = resp.json()
    assert body["id"] > 0
    assert body["brand"] == "腾势"
    assert body["series"] == "腾势D9"
    assert body["mileage_wan"] == 6.05
    assert body["reg_date"] == "2023-05-01"
    assert body["guide_price_wan"] == 48.39
    assert body["created_at"] and body["updated_at"]


def test_list_returns_total_and_items(client, sample_payload):
    _create(client, sample_payload, brand="腾势")
    _create(client, sample_payload, brand="特斯拉")

    resp = client.get("/api/cars")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 2
    assert len(body["items"]) == 2
    assert {item["brand"] for item in body["items"]} == {"腾势", "特斯拉"}


def test_list_filter_by_brand(client, sample_payload):
    _create(client, sample_payload, brand="腾势")
    _create(client, sample_payload, brand="特斯拉")

    body = client.get("/api/cars", params={"brand": "腾势"}).json()
    assert body["total"] == 1
    assert body["items"][0]["brand"] == "腾势"


def test_list_pagination(client, sample_payload):
    for i in range(3):
        _create(client, sample_payload, model_name=f"车型 {i}")

    page1 = client.get("/api/cars", params={"skip": 0, "limit": 2}).json()
    page2 = client.get("/api/cars", params={"skip": 2, "limit": 2}).json()
    assert page1["total"] == 3 and page2["total"] == 3
    assert len(page1["items"]) == 2
    assert len(page2["items"]) == 1
    assert {i["id"] for i in page1["items"]}.isdisjoint({i["id"] for i in page2["items"]})


def test_get_single(client, sample_payload):
    car_id = _create(client, sample_payload).json()["id"]
    resp = client.get(f"/api/cars/{car_id}")
    assert resp.status_code == 200
    assert resp.json()["id"] == car_id


def test_put_updates_fields(client, sample_payload):
    car_id = _create(client, sample_payload).json()["id"]
    resp = client.put(f"/api/cars/{car_id}", json={"city": "上海", "mileage_wan": 8.8})
    assert resp.status_code == 200
    body = resp.json()
    assert body["city"] == "上海"
    assert body["mileage_wan"] == 8.8
    assert body["brand"] == "腾势"  # 未提交的字段保持原值


def test_patch_updates_single_field(client, sample_payload):
    car_id = _create(client, sample_payload).json()["id"]
    resp = client.patch(f"/api/cars/{car_id}", json={"contact": "李四"})
    assert resp.status_code == 200
    assert resp.json()["contact"] == "李四"


def test_delete_returns_204_then_404(client, sample_payload):
    car_id = _create(client, sample_payload).json()["id"]
    assert client.delete(f"/api/cars/{car_id}").status_code == 204
    assert client.get(f"/api/cars/{car_id}").status_code == 404
    assert client.delete(f"/api/cars/{car_id}").status_code == 404


def test_missing_car_returns_404(client):
    assert client.get("/api/cars/987654").status_code == 404
    assert client.put("/api/cars/987654", json={"city": "上海"}).status_code == 404


def test_negative_mileage_rejected(client, sample_payload):
    resp = _create(client, sample_payload, mileage_wan=-1)
    assert resp.status_code == 422
    assert "mileage_wan" in resp.text


def test_blank_brand_rejected(client, sample_payload):
    resp = _create(client, sample_payload, brand="   ")
    assert resp.status_code == 422


def test_future_reg_date_rejected(client, sample_payload):
    resp = _create(client, sample_payload, reg_date="2099-01-01")
    assert resp.status_code == 422


def test_too_old_reg_date_rejected(client, sample_payload):
    resp = _create(client, sample_payload, reg_date="1900-01-01")
    assert resp.status_code == 422


def test_missing_required_field_rejected(client, sample_payload):
    payload = dict(sample_payload)
    payload.pop("city")
    assert client.post("/api/cars", json=payload).status_code == 422


def test_limit_out_of_range_rejected(client):
    assert client.get("/api/cars", params={"limit": 0}).status_code == 422
    assert client.get("/api/cars", params={"limit": 999}).status_code == 422
    assert client.get("/api/cars", params={"skip": -1}).status_code == 422
