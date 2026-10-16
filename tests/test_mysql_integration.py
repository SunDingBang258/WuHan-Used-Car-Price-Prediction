"""MySQL 专属断言。

普通的增删改查与接口行为已经由 test_crud.py / test_cars_api.py 覆盖,
这里只保留「换到别的数据库就会挂」的那几条:
  - 确认跑的是 MySQL 而不是别的库;
  - 确认字符集是 utf8mb4(它能存 emoji, utf8 存不下)。

连接信息由环境变量提供, 与程序完全同源, 没有单独的测试连接串。
"""
from __future__ import annotations

from app import crud, schemas
from app.database import get_engine, get_session_factory


def test_dialect_is_mysql():
    assert get_engine().dialect.name == "mysql"


def test_url_uses_utf8mb4():
    assert "utf8mb4" in str(get_engine().url)


def test_chinese_and_emoji_roundtrip():
    """utf8mb4 才存得下 emoji; 用 utf8/latin1 会报错或丢字符。"""
    session = get_session_factory()()
    try:
        car = crud.create_car(
            session,
            schemas.CarCreate(
                brand="测试🚗",
                series="中文车系",
                model_name="中文车型 2024款",
                mileage_wan=1.0,
                transfer_times=0,
                city="武汉",
            ),
        )
        got = crud.get_car(session, car.id)
        assert got is not None
        assert got.brand == "测试🚗"
        assert got.series == "中文车系"
    finally:
        session.close()
