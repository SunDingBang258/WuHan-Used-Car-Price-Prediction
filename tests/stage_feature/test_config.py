"""配置层: 连接串怎么拼、缺配置会不会明确报错。全程不碰数据库。"""
from __future__ import annotations

import pytest
from app.config import (
    DEFAULT_CHARSET,
    ConfigError,
    build_mysql_url,
    load_settings,
    reset_settings_cache,
)

DB_ENV = {
    "DB_HOST": "127.0.0.1",
    "DB_PORT": "3306",
    "DB_USER": "u",
    "DB_PASSWORD": "p",
    "DB_NAME": "cars",
}

# CI 会注入 AUTO_CREATE_TABLES 之类的变量, 断言默认值前必须清干净
ENV_NAMES = (*DB_ENV, "DB_CHARSET", "DATABASE_URL", "APP_NAME", "DEBUG", "AUTO_CREATE_TABLES")


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    reset_settings_cache()
    yield
    reset_settings_cache()


def _set_all(monkeypatch) -> None:
    for name, value in DB_ENV.items():
        monkeypatch.setenv(name, value)


def test_url_built_from_parts():
    url = build_mysql_url(host="db.example.com", port=3307, user="u", password="p", name="cars")
    assert url == "mysql+pymysql://u:p@db.example.com:3307/cars?charset=utf8mb4"


def test_charset_defaults_to_utf8mb4(monkeypatch):
    """不填 DB_CHARSET 时用 utf8mb4, 否则 emoji 存不进去。"""
    _set_all(monkeypatch)
    assert load_settings().sqlalchemy_url.endswith(f"charset={DEFAULT_CHARSET}")


def test_missing_config_lists_exactly_what_is_missing(monkeypatch):
    monkeypatch.setenv("DB_HOST", "127.0.0.1")
    with pytest.raises(ConfigError) as excinfo:
        load_settings()
    missing = str(excinfo.value).split("配置: ", 1)[1].split("。", 1)[0]
    for name in ("DB_PORT", "DB_USER", "DB_PASSWORD", "DB_NAME"):
        assert name in missing
    assert "DB_HOST" not in missing


def test_database_url_wins_over_parts(monkeypatch):
    _set_all(monkeypatch)
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///./tmp.db")
    settings = load_settings()
    assert settings.sqlalchemy_url == "sqlite+pysqlite:///./tmp.db"
    assert settings.is_mysql is False


def test_invalid_port_is_rejected(monkeypatch):
    _set_all(monkeypatch)
    monkeypatch.setenv("DB_PORT", "not-a-number")
    with pytest.raises(ConfigError, match="DB_PORT"):
        load_settings()
