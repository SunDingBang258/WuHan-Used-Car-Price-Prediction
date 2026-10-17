"""健康检查: 不碰业务逻辑, 只确认服务和数据库都在。"""
from __future__ import annotations

from app.database import get_engine


def test_live_engine_is_mysql_with_utf8mb4():
    """跑测试的库必须真是 MySQL + utf8mb4, 否则 CI 悄悄退化也看不出来。"""
    engine = get_engine()
    assert engine.dialect.name == "mysql"
    assert "utf8mb4" in str(engine.url)


def test_api_health_is_ok(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["app"] and body["version"]


def test_db_health_reports_mysql(client):
    resp = client.get("/api/health/db")
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"status": "ok", "database": "mysql"}
