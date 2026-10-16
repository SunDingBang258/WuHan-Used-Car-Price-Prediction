"""应用冒烟测试: 用 TestClient 在进程内把应用整体跑一遍。

不依赖已部署的服务, 所以本地和任意 CI 阶段都能执行。
"""
from __future__ import annotations


def test_health_endpoint(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_database_endpoint(client):
    resp = client.get("/api/health/db")
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "ok"


def test_homepage_renders_form(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert "录入车辆参数" in resp.text
    assert 'action="/cars"' in resp.text


def test_full_crud_roundtrip(client):
    """从新增到删除串一遍, 确认各接口之间接得上。"""
    payload = {
        "brand": "冒烟测试",
        "series": "SMOKE",
        "model_name": "冒烟测试车型 2024款",
        "reg_date": "2024-01-01",
        "mileage_wan": 1.5,
        "transfer_times": 0,
        "city": "武汉",
    }
    created = client.post("/api/cars", json=payload)
    assert created.status_code == 201, created.text
    car_id = created.json()["id"]

    try:
        assert client.get(f"/api/cars/{car_id}").status_code == 200
        listed = client.get("/api/cars", params={"brand": "冒烟测试"})
        assert listed.status_code == 200
        assert listed.json()["total"] >= 1

        updated = client.put(f"/api/cars/{car_id}", json={"city": "上海"})
        assert updated.status_code == 200
        assert updated.json()["city"] == "上海"

        assert "冒烟测试" in client.get("/").text
    finally:
        assert client.delete(f"/api/cars/{car_id}").status_code == 204

    assert client.get(f"/api/cars/{car_id}").status_code == 404
