"""应用整体冒烟: 用 TestClient 在进程内把应用跑一遍, 不依赖已部署的服务。"""
from __future__ import annotations


def test_homepage_renders(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert "录入车辆参数" in resp.text


def test_health_endpoints(client):
    assert client.get("/api/health").json()["status"] == "ok"
    db = client.get("/api/health/db")
    assert db.status_code == 200, db.text
    assert db.json()["status"] == "ok"


def test_full_crud_roundtrip(client):
    """新增 -> 查 -> 改 -> 列表里能看到 -> 删, 确认各接口接得上。"""
    payload = {
        "brand": "特斯拉",
        "series": "Model Y",
        "car_age_years": 1.0,
        "mileage_wan": 1.5,
        "zero_transfer": True,
        "factory_warranty": False,
        "near_new": False,
    }
    created = client.post("/api/cars", json=payload)
    assert created.status_code == 201, created.text
    body = created.json()
    car_id = body["id"]
    assert body["brand_id"] and body["series_id"]

    try:
        assert client.get(f"/api/cars/{car_id}").status_code == 200
        assert client.get("/api/cars", params={"brand": "特斯拉"}).json()["total"] >= 1
        updated = client.put(f"/api/cars/{car_id}", json={"near_new": True})
        assert updated.json()["near_new"] is True
        assert "Model Y" in client.get("/").text
    finally:
        assert client.delete(f"/api/cars/{car_id}").status_code == 204

    assert client.get(f"/api/cars/{car_id}").status_code == 404
