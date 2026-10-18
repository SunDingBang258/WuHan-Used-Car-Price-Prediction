"""健康检查: 不碰业务逻辑, 只确认服务和数据库都在。"""
from __future__ import annotations


def test_api_health_is_ok(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["app"] and body["version"]


def test_db_health_is_ok(client):
    """这一个同时守住两件事: 数据库连得上, 且真的是 MySQL。

    之前拆成两个测试(live_engine_* + db_health_*), 断言的内容高度重叠, 合并了。
    """
    resp = client.get("/api/health/db")
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"status": "ok", "database": "mysql"}
