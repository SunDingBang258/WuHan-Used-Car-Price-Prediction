"""JSON API 路由。

给前端页面用, 也给后续的价格预测服务/脚本用。
品牌/车系传名称, 后台用 app.reference 查表补 ID 与统计特征。
"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session

from app import __version__, crud, predictor, reference, schemas
from app.config import get_settings
from app.database import check_connection, get_db

router = APIRouter(prefix="/api", tags=["cars"])

# 用 Annotated 标注依赖, 这是现代 FastAPI 的推荐写法:
# 依赖写在类型里而不是参数默认值里, 签名更干净。
DbSession = Annotated[Session, Depends(get_db)]


def _resolve(brand: str, series: str) -> dict:
    try:
        return reference.lookup(brand, series)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/health", response_model=schemas.HealthOut, summary="存活探针")
def health() -> schemas.HealthOut:
    """不碰数据库, 用于容器存活检查。"""
    settings = get_settings()
    return schemas.HealthOut(status="ok", app=settings.app_name, version=__version__)


@router.get("/health/db", response_model=schemas.DbHealthOut, summary="数据库探针")
def health_db(db: DbSession) -> schemas.DbHealthOut:
    """连不上数据库返回 503, 方便 CI 与运维判断。"""
    if not check_connection():
        raise HTTPException(status_code=503, detail="数据库不可用")
    dialect = db.bind.dialect.name if db.bind is not None else "unknown"
    return schemas.DbHealthOut(status="ok", database=dialect)


@router.get("/cars", response_model=schemas.CarListOut, summary="查询车源参数列表")
def list_cars(
    db: DbSession,
    brand: Annotated[str | None, Query(description="按品牌过滤")] = None,
    skip: Annotated[int, Query(ge=0, description="跳过条数")] = 0,
    limit: Annotated[int, Query(ge=1, le=200, description="每页条数")] = 50,
) -> schemas.CarListOut:
    items, total = crud.list_cars(db, brand=brand, skip=skip, limit=limit)
    return schemas.CarListOut(total=total, items=[schemas.CarOut.model_validate(i) for i in items])


@router.post("/predict", response_model=schemas.PredictOut, summary="预估售价")
def predict_price(payload: schemas.CarInput) -> schemas.PredictOut:
    """不写库, 只把参数喂给模型返回估价。"""
    try:
        price = predictor.predict(**payload.model_dump())
    except ValueError as exc:  # 品牌/车系不在 reference.json 里
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return schemas.PredictOut(price_wan=price)


@router.post("/cars", response_model=schemas.CarOut, status_code=201, summary="新增车源参数")
def create_car(payload: schemas.CarCreate, db: DbSession) -> schemas.CarOut:
    features = _resolve(payload.brand, payload.series)
    return schemas.CarOut.model_validate(crud.create_car(db, payload, features))


@router.get("/cars/{car_id}", response_model=schemas.CarOut, summary="查询单条")
def get_car(car_id: int, db: DbSession) -> schemas.CarOut:
    car = crud.get_car(db, car_id)
    if car is None:
        raise HTTPException(status_code=404, detail=f"车源 {car_id} 不存在")
    return schemas.CarOut.model_validate(car)


@router.put("/cars/{car_id}", response_model=schemas.CarOut, summary="整体更新")
def update_car(car_id: int, payload: schemas.CarUpdate, db: DbSession) -> schemas.CarOut:
    touched = payload.model_dump(exclude_unset=True)
    if ("brand" in touched) != ("series" in touched):
        raise HTTPException(status_code=422, detail="品牌和车系必须一起改")
    features = _resolve(touched["brand"], touched["series"]) if "brand" in touched else None
    car = crud.update_car(db, car_id, payload, features)
    if car is None:
        raise HTTPException(status_code=404, detail=f"车源 {car_id} 不存在")
    return schemas.CarOut.model_validate(car)


@router.patch("/cars/{car_id}", response_model=schemas.CarOut, summary="局部更新")
def patch_car(car_id: int, payload: schemas.CarUpdate, db: DbSession) -> schemas.CarOut:
    return update_car(car_id, payload, db)


@router.delete("/cars/{car_id}", status_code=204, summary="删除")
def delete_car(car_id: int, db: DbSession) -> Response:
    if not crud.delete_car(db, car_id):
        raise HTTPException(status_code=404, detail=f"车源 {car_id} 不存在")
    return Response(status_code=204)
