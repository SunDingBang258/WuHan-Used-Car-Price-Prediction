"""HTML 页面路由(服务端渲染, 表单直接 POST, 不需要前后端分离)。"""
from __future__ import annotations

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app import crud, predictor, reference, schemas
from app.database import get_db

ROOT = Path(__file__).resolve().parent.parent.parent
templates = Jinja2Templates(directory=str(ROOT / "templates"))

router = APIRouter(tags=["pages"])

DbSession = Annotated[Session, Depends(get_db)]

# 三个标记字段在页面上是「是/否」下拉框, 统一成 "1"/"0" 再交给 Pydantic
FLAG_FIELDS = ("zero_transfer", "factory_warranty", "near_new")
TRUE_WORDS = ("1", "true", "on", "yes", "是")


def _clean_form(form: dict) -> dict:
    """把 HTML 表单交上来的字符串整理成 Pydantic 能吃的形态。"""
    data: dict = {}
    for key, value in form.items():
        value = (value or "").strip()
        data[key] = value if value != "" else None
    for key in FLAG_FIELDS:
        raw = str(form.get(key, "0")).strip().lower()
        data[key] = "1" if raw in TRUE_WORDS else "0"
    return data


def _format_error(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        parts = []
        for err in exc.errors():
            loc = ".".join(str(x) for x in err.get("loc", ()))
            parts.append(f"{loc}: {err.get('msg')}")
        return "; ".join(parts)
    return str(exc)


def _missing_car(request: Request, car_id: int) -> HTMLResponse:
    return templates.TemplateResponse(
        request, "error.html", {"message": f"车源 {car_id} 不存在"}, status_code=404
    )


def _render_index(request: Request, db: Session, *, error=None, form=None, status_code=200):
    items, total = crud.list_cars(db, limit=100)
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "cars": items,
            "total": total,
            "error": error,
            "form": form or {},
            "brands": reference.brand_names(),
            "series": reference.series_names(),
            "series_by_brand": reference.series_by_brand(),
        },
        status_code=status_code,
    )


def _render_edit(request: Request, car, *, error=None, status_code=200):
    return templates.TemplateResponse(
        request,
        "edit.html",
        {
            "car": car,
            "error": error,
            "brands": reference.brand_names(),
            "series": reference.series_names(),
            "series_by_brand": reference.series_by_brand(),
        },
        status_code=status_code,
    )


@router.get("/", response_class=HTMLResponse, summary="首页: 录入表单 + 列表")
def index(request: Request, db: DbSession) -> HTMLResponse:
    return _render_index(request, db)


@router.post("/cars", response_class=HTMLResponse, summary="表单提交: 新增")
async def create_from_form(request: Request, db: DbSession):
    form = dict(await request.form())
    try:
        payload = schemas.CarCreate(**_clean_form(form))
        features = reference.lookup(payload.brand, payload.series)
    except (ValidationError, ValueError) as exc:
        return _render_index(request, db, error=_format_error(exc), form=form, status_code=400)
    car = crud.create_car(db, payload, features)
    return RedirectResponse(url=f"/cars/{car.id}", status_code=303)


@router.get("/cars/{car_id}", response_class=HTMLResponse, summary="估价结果页")
def car_result(request: Request, car_id: int, db: DbSession):
    car = crud.get_car(db, car_id)
    if car is None:
        return _missing_car(request, car_id)
    price = predictor.predict(
        brand=car.brand,
        series=car.series,
        car_age_years=float(car.car_age_years),
        mileage_wan=float(car.mileage_wan),
        zero_transfer=car.zero_transfer,
        factory_warranty=car.factory_warranty,
        near_new=car.near_new,
    )
    return templates.TemplateResponse(
        request, "prediction.html", {"car": car, "price": price}
    )


@router.get("/cars/{car_id}/edit", response_class=HTMLResponse, summary="编辑页")
def edit_page(request: Request, car_id: int, db: DbSession):
    car = crud.get_car(db, car_id)
    if car is None:
        return _missing_car(request, car_id)
    return _render_edit(request, car)


@router.post("/cars/{car_id}/edit", response_class=HTMLResponse, summary="表单提交: 修改")
async def update_from_form(request: Request, car_id: int, db: DbSession):
    car = crud.get_car(db, car_id)
    if car is None:
        return _missing_car(request, car_id)
    form = dict(await request.form())
    try:
        payload = schemas.CarUpdate(**_clean_form(form))
        touched = payload.model_dump(exclude_unset=True)
        features = None
        if "brand" in touched and "series" in touched:
            features = reference.lookup(touched["brand"], touched["series"])
        elif "brand" in touched or "series" in touched:
            raise ValueError("品牌和车系必须一起改")
    except (ValidationError, ValueError) as exc:
        return _render_edit(request, car, error=_format_error(exc), status_code=400)
    crud.update_car(db, car_id, payload, features)
    return RedirectResponse(url="/", status_code=303)


@router.post("/cars/{car_id}/delete", summary="表单提交: 删除")
def delete_from_form(request: Request, car_id: int, db: DbSession):
    if not crud.delete_car(db, car_id):
        return _missing_car(request, car_id)
    return RedirectResponse(url="/", status_code=303)
