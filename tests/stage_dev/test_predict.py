"""价格预测的测试: API 接口 + 结果页。"""

from __future__ import annotations

import pytest

from app import predictor


def _payload():
    return {
        "brand": "宝马",
        "series": "宝马X5",
        "car_age_years": 3.5,
        "mileage_wan": 6.05,
        "zero_transfer": True,
        "factory_warranty": False,
        "near_new": False,
    }


def test_predict_returns_plausible_price():
    price = predictor.predict(**_payload())
    # 宝马X5 车龄 3.5 年, 应该落在合理量级
    assert 5 < price < 200


def test_predict_unknown_series_raises():
    with pytest.raises(ValueError, match="不在可选范围"):
        predictor.predict(**{**_payload(), "series": "不存在的车系"})


def test_predict_api(client):
    resp = client.post("/api/predict", json=_payload())
    assert resp.status_code == 200, resp.text
    assert resp.json()["price_wan"] > 0


def test_predict_api_unknown_brand_rejected(client):
    resp = client.post("/api/predict", json={**_payload(), "brand": "不存在的品牌"})
    assert resp.status_code == 422
    assert "不在可选范围" in resp.text


def test_form_submit_redirects_to_result_page(client):
    form = {
        "brand": "宝马", "series": "宝马X5", "car_age_years": "3.5", "mileage_wan": "6.05",
        "zero_transfer": "1", "factory_warranty": "0", "near_new": "0",
    }
    resp = client.post("/cars", data=form, follow_redirects=False)
    assert resp.status_code == 303
    location = resp.headers["location"]
    assert location.startswith("/cars/") and not location.endswith("/edit")

    page = client.get(location)
    assert page.status_code == 200
    assert "估价结果" in page.text
    assert "万元" in page.text


def test_result_page_missing_car_returns_404(client):
    assert client.get("/cars/987654").status_code == 404
