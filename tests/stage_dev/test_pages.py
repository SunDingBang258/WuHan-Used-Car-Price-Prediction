"""HTML 页面: 表单渲染、提交、编辑、删除(服务端渲染路径)。"""
from __future__ import annotations


def _form(**overrides):
    data = {
        "brand": "特斯拉",
        "series": "Model Y",
        "car_age_years": "1.5",
        "mileage_wan": "2.5",
        "zero_transfer": "1",
        "factory_warranty": "1",
        "near_new": "0",
    }
    data.update(overrides)
    return data


def test_index_renders_form_with_datalists(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert 'action="/cars"' in resp.text
    assert 'list="brand-options"' in resp.text
    assert 'list="series-options"' in resp.text
    assert 'value="特斯拉"' in resp.text
    assert "还没有数据" in resp.text


def test_form_submit_creates_and_fills_lookup(client):
    from app import reference

    resp = client.post("/cars", data=_form(), follow_redirects=False)
    assert resp.status_code == 303

    body = client.get("/api/cars").json()["items"][0]
    expect = reference.lookup("特斯拉", "Model Y")
    assert body["series_id"] == expect["series_id"]
    assert "Model Y" in client.get("/").text


def test_form_submit_flags_become_booleans(client):
    client.post("/cars", data=_form(), follow_redirects=False)
    body = client.get("/api/cars").json()["items"][0]
    assert body["zero_transfer"] is True
    assert body["factory_warranty"] is True
    assert body["near_new"] is False


def test_form_submit_unknown_brand_returns_400(client):
    resp = client.post("/cars", data=_form(brand="不存在的品牌"), follow_redirects=False)
    assert resp.status_code == 400
    assert "提交失败" in resp.text and "不在可选范围" in resp.text


def test_edit_submit_updates_and_recomputes(client):
    from app import reference

    client.post("/cars", data=_form(), follow_redirects=False)
    car_id = client.get("/api/cars").json()["items"][0]["id"]

    resp = client.post(
        f"/cars/{car_id}/edit",
        data=_form(brand="宝马", series="宝马X5", zero_transfer="0"),
        follow_redirects=False,
    )
    assert resp.status_code == 303
    body = client.get(f"/api/cars/{car_id}").json()
    assert body["series_id"] == reference.lookup("宝马", "宝马X5")["series_id"]
    assert body["zero_transfer"] is False


def test_delete_from_page(client):
    client.post("/cars", data=_form(), follow_redirects=False)
    car_id = client.get("/api/cars").json()["items"][0]["id"]

    resp = client.post(f"/cars/{car_id}/delete", follow_redirects=False)
    assert resp.status_code == 303
    assert "还没有数据" in client.get("/").text
