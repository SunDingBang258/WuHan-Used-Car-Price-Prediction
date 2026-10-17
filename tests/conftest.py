"""pytest 公共夹具。

测试直接跑在**环境变量配置的那个数据库**上(CI 由 workflow 的 services.mysql 提供),
不另建替身库、不替换 get_db —— 这样测到的就是程序真实运行的代码路径。

夹具按需触发: 只有真正用到数据库的测试才会建表/清表,
所以 test_database_config.py 这类纯配置测试不需要数据库也能跑。

⚠️ 用到数据库的测试会在开始前清空 cars 表, 所以跑测试请指向一个可丢弃的库:
    DB_NAME=car_predict_test pytest
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest
from app import models
from app.database import Base, get_engine, get_session_factory
from fastapi.testclient import TestClient
from sqlalchemy import delete

# 注意: 不要在这里导入 app.main —— 它在模块级就会构造应用并读取配置,
# 会让纯配置测试也被迫要求一份可用的数据库配置。


@pytest.fixture(scope="session")
def schema():
    """建表(已存在则跳过), 整个测试会话只做一次。"""
    Base.metadata.create_all(bind=get_engine())
    yield


@pytest.fixture()
def clean_db(schema):
    """用到数据库的测试开始前清空数据, 保证测试之间互不影响。"""
    with get_engine().begin() as conn:
        conn.execute(delete(models.Car))
    yield


@pytest.fixture()
def db_session(clean_db):
    """直接操作数据库的会话(给 crud 层测试用)。"""
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def client(clean_db):
    """FastAPI 测试客户端, 用程序自己的 get_db, 不做任何替换。"""
    from app.main import create_app

    with TestClient(create_app()) as test_client:
        yield test_client


@pytest.fixture()
def sample_payload():
    """一份合法的车辆参数。品牌/车系必须是 app/reference.json 里存在的组合。"""
    return {
        "brand": "特斯拉",
        "series": "Model Y",
        "car_age_years": 1.5,
        "mileage_wan": 2.5,
        "zero_transfer": True,
        "factory_warranty": True,
        "near_new": False,
    }
