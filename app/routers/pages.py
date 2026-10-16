"""HTML 页面路由(服务端渲染, 表单直接 POST, 不需要前后端分离)。"""
from __future__ import annotations

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app import crud, schemas
from app.database import get_db

ROOT = Path(__file__).resolve().parent.parent.parent
templates = Jinja2Templates(directory=str(ROOT / "templates"))

router = APIRouter(tags=["pages"])

DbSession = Annotated[Session, Depends(get_db)]

# 表单里空字符串要还原成 None, 否则数字/日期字段会校验失败
NUMERIC_WITH_DEFAULT = {"transfer_times": 0}


def _clean_form(form: dict) -> dict:
    """把 HTML 表单交上来的字符串整理成 Pydantic 能吃的形态。"""
    data: dict = {}
    for key, value in form.items():
        value = (value or "").strip()
        data[key] = value if value != "" else None
    for key, default in NUMERIC_WITH_DEFAULT.items():
        if data.get(key) is None:
            data[key] = default
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


@router.get("/", response_class=HTMLResponse, summary="首页: 录入表单 + 列表")
def index(request: Request, db: DbSession) -> HTMLResponse:
    items, total = crud.list_cars(db, limit=100)
    return templates.TemplateResponse(
        request, "index.html", {"cars": items, "total": total, "error": None, "form": {}}
    )


@router.post("/cars", response_class=HTMLResponse, summary="表单提交: 新增")
async def create_from_form(request: Request, db: DbSession):
    form = dict(await request.form())
    try:
        payload = schemas.CarCreate(**_clean_form(form))
    except (ValidationError, ValueError) as exc:
        items, total = crud.list_cars(db, limit=100)
        return templates.TemplateResponse(
            request,
            "index.html",
            {"cars": items, "total": total, "error": _format_error(exc), "form": form},
            status_code=400,
        )
    crud.create_car(db, payload)
    return RedirectResponse(url="/", status_code=303)


@router.get("/cars/{car_id}/edit", response_class=HTMLResponse, summary="编辑页")
def edit_page(request: Request, car_id: int, db: DbSession):
    car = crud.get_car(db, car_id)
    if car is None:
        return _missing_car(request, car_id)
    return templates.TemplateResponse(request, "edit.html", {"car": car, "error": None})


@router.post("/cars/{car_id}/edit", response_class=HTMLResponse, summary="表单提交: 修改")
async def update_from_form(request: Request, car_id: int, db: DbSession):
    form = dict(await request.form())
    try:
        payload = schemas.CarUpdate(**_clean_form(form))
    except (ValidationError, ValueError) as exc:
        car = crud.get_car(db, car_id)
        if car is None:
            return _missing_car(request, car_id)
        return templates.TemplateResponse(
            request, "edit.html", {"car": car, "error": _format_error(exc)}, status_code=400
        )
    if crud.update_car(db, car_id, payload) is None:
        return _missing_car(request, car_id)
    return RedirectResponse(url="/", status_code=303)


@router.post("/cars/{car_id}/delete", summary="表单提交: 删除")
def delete_from_form(request: Request, car_id: int, db: DbSession):
    if not crud.delete_car(db, car_id):
        return _missing_car(request, car_id)
    return RedirectResponse(url="/", status_code=303)
