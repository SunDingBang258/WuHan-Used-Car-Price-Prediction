"""应用配置。

配置只有一个来源: 环境变量(本地开发可用仓库根目录的 .env)。
**数据库连接不设任何兜底默认值** —— 缺了就在启动时明确报错,
而不是拿着错误的默认账号去连库, 把问题推到更难定位的地方。

  - 本地开发: cp .env.example .env 填好(会自动加载)
  - CI: 在 workflow 的 env 段注入(见 .github/workflows/*.yml)
  - 生产: 由部署环境注入

其它模块只调用 get_settings(), 不直接读 os.environ。
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote_plus

from dotenv import load_dotenv

# 仓库根目录下的 .env, 存在才读。
# override=False: 真实环境变量优先, 不会被文件里的值盖掉 ——
# CI 与容器都是直接注入环境变量的, 那边没有 .env, 互不影响。
ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env", override=False)

# 走分项拼连接串时必须提供的变量
DB_VARS = ("DB_HOST", "DB_PORT", "DB_USER", "DB_PASSWORD", "DB_NAME")

# 字符集给个默认值: 必须 utf8mb4, 否则 emoji 之类的字符存不进去
DEFAULT_CHARSET = "utf8mb4"


class ConfigError(RuntimeError):
    """配置缺失或不合法。启动时直接失败, 不带错误默认值去连库。"""


def build_mysql_url(
    host: str, port: int, user: str, password: str, name: str, charset: str = DEFAULT_CHARSET
) -> str:
    """把分项拼成 SQLAlchemy 连接串; 用户名/密码里的特殊字符会被转义。"""
    return (
        f"mysql+pymysql://{quote_plus(user)}:{quote_plus(password)}"
        f"@{host}:{port}/{name}?charset={charset}"
    )


def _get_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _require(name: str) -> str:
    value = (os.getenv(name) or "").strip()
    if not value:
        raise ConfigError(f"缺少环境变量 {name}")
    return value


def _require_int(name: str) -> int:
    raw = _require(name)
    try:
        return int(raw)
    except ValueError:
        raise ConfigError(f"环境变量 {name} 必须是整数, 当前为 {raw!r}") from None


@dataclass(frozen=True)
class Settings:
    """不可变配置对象, 字段在构造时就已解析完成。"""

    app_name: str
    debug: bool
    auto_create_tables: bool
    sqlalchemy_url: str

    @property
    def is_mysql(self) -> bool:
        return self.sqlalchemy_url.startswith("mysql")


def load_settings() -> Settings:
    """读环境变量并解析; 每次调用都重新读(测试需要)。"""
    database_url = (os.getenv("DATABASE_URL") or "").strip()
    if database_url:
        # 直接给了完整连接串, 就不再要求分项
        url = database_url
    else:
        missing = [name for name in DB_VARS if not (os.getenv(name) or "").strip()]
        if missing:
            raise ConfigError(
                "缺少数据库连接配置: "
                + ", ".join(missing)
                + "。请执行 `cp .env.example .env` 并填写, 或直接设置 DATABASE_URL。"
            )
        url = build_mysql_url(
            host=_require("DB_HOST"),
            port=_require_int("DB_PORT"),
            user=_require("DB_USER"),
            password=_require("DB_PASSWORD"),
            name=_require("DB_NAME"),
            charset=os.getenv("DB_CHARSET", DEFAULT_CHARSET),
        )

    return Settings(
        app_name=os.getenv("APP_NAME", "武汉二手车价格预测"),
        debug=_get_bool("DEBUG", False),
        auto_create_tables=_get_bool("AUTO_CREATE_TABLES", True),
        sqlalchemy_url=url,
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return load_settings()


def reset_settings_cache() -> None:
    """测试里改完环境变量后调用, 让下次 get_settings() 重新读取。"""
    get_settings.cache_clear()
