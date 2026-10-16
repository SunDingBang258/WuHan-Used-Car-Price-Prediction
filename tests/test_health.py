"""健康检查接口测试。"""
from __future__ import annotations


def test_api_health_is_ok(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["version"]
    assert body["app"]


def test_db_health_reports_mysql(client):
    """断言方言是 mysql, 防止 CI 悄悄退化成别的库还"跑绿"。"""
    resp = client.get("/api/health/db")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "database": "mysql"}


def test_openapi_document_is_served(client):
    resp = client.get("/openapi.json")
    assert resp.status_code == 200
    paths = resp.json()["paths"]
    assert "/api/cars" in paths
    assert "/api/cars/{car_id}" in paths
