"""数据访问层: 只做增删改查, 不掺业务规则, 方便单独测试。"""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import models, schemas


def list_cars(
    db: Session,
    *,
    brand: str | None = None,
    city: str | None = None,
    skip: int = 0,
    limit: int = 50,
) -> tuple[list[models.Car], int]:
    """按条件分页查询, 返回 (当前页记录, 总条数)。"""
    stmt = select(models.Car)
    count_stmt = select(func.count()).select_from(models.Car)
    if brand:
        stmt = stmt.where(models.Car.brand == brand)
        count_stmt = count_stmt.where(models.Car.brand == brand)
    if city:
        stmt = stmt.where(models.Car.city == city)
        count_stmt = count_stmt.where(models.Car.city == city)

    stmt = stmt.order_by(models.Car.id.desc()).offset(skip).limit(limit)
    items = list(db.execute(stmt).scalars())
    total = int(db.execute(count_stmt).scalar_one())
    return items, total


def get_car(db: Session, car_id: int) -> models.Car | None:
    return db.get(models.Car, car_id)


def create_car(db: Session, payload: schemas.CarCreate) -> models.Car:
    car = models.Car(**payload.model_dump())
    db.add(car)
    db.commit()
    db.refresh(car)
    return car


def update_car(db: Session, car_id: int, payload: schemas.CarUpdate) -> models.Car | None:
    car = db.get(models.Car, car_id)
    if car is None:
        return None
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(car, key, value)
    db.commit()
    db.refresh(car)
    return car


def delete_car(db: Session, car_id: int) -> bool:
    car = db.get(models.Car, car_id)
    if car is None:
        return False
    db.delete(car)
    db.commit()
    return True
