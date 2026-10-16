"""HTML 页面测试: 表单渲染、提交、编辑、删除(服务端渲染路径)。"""
from __future__ import annotations


def _form(**overrides):
    data = {
        "brand": "特斯拉",
        "series": "Model Y",
        "model_name": "Model Y 2024款 长续航全轮驱动版",
        "reg_date": "2024-03-01",
        "mileage_wan": "2.5",
        "transfer_times": "1",
        "city": "武汉",
        "gearbox": "自动",
        "fuel_type": "纯电动",
        "displacement_l": "",
        "guide_price_wan": "29.99",
        "contact": "李四",
    }
    data.update(overrides)
    return data


def test_index_renders_form_and_empty_state(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert 'action="/cars"' in resp.text
    assert "录入车辆参数" in resp.text
    assert "还没有数据" in resp.text


def test_static_css_is_served(client):
    resp = client.get("/static/style.css")
    assert resp.status_code == 200
    assert "--accent" in resp.text


def test_form_submit_creates_and_redirects(client):
    resp = client.post("/cars", data=_form(), follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/"

    page = client.get("/")
    assert "Model Y" in page.text
    assert "李四" in page.text
    assert "共 1 条" in page.text


def test_form_submit_with_empty_optional_fields(client):
    """空的可选字段(排量/指导价/提交人)不应导致校验失败。"""
    resp = client.post(
        "/cars",
        data=_form(displacement_l="", guide_price_wan="", contact="", reg_date=""),
        follow_redirects=False,
    )
    assert resp.status_code == 303


def test_form_submit_invalid_returns_400_with_message(client):
    resp = client.post("/cars", data=_form(mileage_wan="-5"), follow_redirects=False)
    assert resp.status_code == 400
    assert "提交失败" in resp.text
    assert "mileage_wan" in resp.text


def test_form_submit_future_date_returns_400(client):
    resp = client.post("/cars", data=_form(reg_date="2099-01-01"), follow_redirects=False)
    assert resp.status_code == 400
    assert "提交失败" in resp.text


def test_edit_page_prefills_values(client):
    client.post("/cars", data=_form(), follow_redirects=False)
    car_id = client.get("/api/cars").json()["items"][0]["id"]

    resp = client.get(f"/cars/{car_id}/edit")
    assert resp.status_code == 200
    assert f'action="/cars/{car_id}/edit"' in resp.text
    assert "Model Y" in resp.text
    assert "特斯拉" in resp.text


def test_edit_submit_updates_record(client):
    client.post("/cars", data=_form(), follow_redirects=False)
    car_id = client.get("/api/cars").json()["items"][0]["id"]

    resp = client.post(f"/cars/{car_id}/edit", data=_form(city="上海"), follow_redirects=False)
    assert resp.status_code == 303
    assert client.get(f"/api/cars/{car_id}").json()["city"] == "上海"


def test_edit_submit_invalid_returns_400(client):
    client.post("/cars", data=_form(), follow_redirects=False)
    car_id = client.get("/api/cars").json()["items"][0]["id"]

    resp = client.post(f"/cars/{car_id}/edit", data=_form(mileage_wan="abc"), follow_redirects=False)
    assert resp.status_code == 400


def test_edit_missing_car_returns_404(client):
    assert client.get("/cars/987654/edit").status_code == 404
    assert client.post("/cars/987654/edit", data=_form()).status_code == 404


def test_delete_from_page(client):
    client.post("/cars", data=_form(), follow_redirects=False)
    car_id = client.get("/api/cars").json()["items"][0]["id"]

    resp = client.post(f"/cars/{car_id}/delete", follow_redirects=False)
    assert resp.status_code == 303
    assert client.get("/api/cars").json()["total"] == 0
    assert "还没有数据" in client.get("/").text


def test_delete_missing_car_from_page_returns_404(client):
    assert client.post("/cars/987654/delete").status_code == 404
