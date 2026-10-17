"""FastAPI 应用装配。

用工厂函数 create_app(), 好处是测试可以隔离地建多个实例,
不会共享全局状态(见 tests/conftest.py)。
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app import __version__
from app.config import get_settings
from app.database import init_db
from app.routers import cars, pages

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = ROOT / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动/关闭钩子。"""
    if get_settings().auto_create_tables:
        try:
            init_db()
        except Exception as exc:  # noqa: BLE001
            # 数据库没起来不应该让整个应用起不来;
            # 具体状态由 /api/health/db 暴露, 便于 CI 与运维定位。
            logger.warning("启动时建表失败: %s", exc)
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        version=__version__,
        description="保存用户提交的二手车参数, 供后续价格预测使用。",
        lifespan=lifespan,
    )
    if STATIC_DIR.is_dir():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
    app.include_router(cars.router)
    app.include_router(pages.router)
    return app


app = create_app()


if __name__ == "__main__":
    # 方便在 IDE 里直接 Run / Debug, 等价于:
    #   uvicorn app.main:app --host 127.0.0.1 --port 8000
    import sys

    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))

    import uvicorn

    uvicorn.run("app.main:app", host="127.0.0.1", port=8000)
