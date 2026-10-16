"""数据库接入层 —— MySQL 的**唯一**配置入口, 全项目复用。

为什么单独成文件:
  - 引擎 / 会话工厂只在这里创建一次, 各处直接复用, 不重复写连接串;
  - 换库(MySQL -> SQLite)只改 DATABASE_URL, 业务代码零改动;
  - 测试可以直接覆盖 get_db 依赖, 不需要真的连 MySQL。

对外提供:
  Base                 所有 ORM 模型的基类
  get_engine()         惰性单例引擎
  get_session_factory()会话工厂
  get_db()             FastAPI 依赖: 每请求一个会话, 用完必关
  init_db()            建表
  check_connection()   探活
  reset_engine()       测试用: 丢弃已缓存的引擎
"""
from __future__ import annotations

import logging
from collections.abc import Iterator

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings

logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    """所有 ORM 模型的基类。"""


_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None


def _mask(url: str) -> str:
    """日志里不打印密码。"""
    if "@" not in url:
        return url
    head, _, tail = url.rpartition("@")
    scheme, sep, cred = head.partition("://")
    if not sep:
        return f"***@{tail}"
    return f"{scheme}://{cred.split(':')[0]}:***@{tail}"


def _engine_kwargs(url: str) -> dict:
    if url.startswith("sqlite"):
        return {"connect_args": {"check_same_thread": False}}
    # MySQL: 探活 + 回收, 避免连接被服务端掐断后拿到坏连接
    return {
        "pool_pre_ping": True,
        "pool_recycle": 3600,
        "pool_size": 5,
        "max_overflow": 10,
    }


def get_engine() -> Engine:
    """惰性创建并缓存引擎。"""
    global _engine
    if _engine is None:
        url = get_settings().sqlalchemy_url
        _engine = create_engine(
            url,
            echo=get_settings().debug,
            future=True,
            **_engine_kwargs(url),
        )
        logger.info("数据库引擎已创建: %s", _mask(url))
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    global _session_factory
    if _session_factory is None:
        _session_factory = sessionmaker(
            bind=get_engine(),
            autoflush=False,
            expire_on_commit=False,
            future=True,
        )
    return _session_factory


def get_db() -> Iterator[Session]:
    """FastAPI 依赖: 每个请求一个会话, 请求结束一定关闭。"""
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()


def init_db() -> None:
    """建表(已存在则跳过)。"""
    from app import models  # noqa: F401  导入以注册元数据

    Base.metadata.create_all(bind=get_engine())
    logger.info("数据表已就绪(%d 张)", len(Base.metadata.tables))


def check_connection() -> bool:
    """探活: 能跑通 SELECT 1 就算通。"""
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("数据库连接失败: %s", exc)
        return False


def reset_engine() -> None:
    """测试用: 丢弃缓存的引擎与会话工厂。"""
    global _engine, _session_factory
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _session_factory = None
