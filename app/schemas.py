"""请求 / 响应的数据结构与校验规则。"""
from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

MIN_YEAR = 1990


class CarBase(BaseModel):
    """一辆车的输入参数(也是价格预测模型的特征)。"""

    brand: str = Field(..., min_length=1, max_length=50, description="品牌")
    series: str = Field(..., min_length=1, max_length=80, description="车系")
    model_name: str = Field(..., min_length=1, max_length=120, description="车型")
    reg_date: date | None = Field(None, description="上牌时间")
    mileage_wan: float = Field(..., ge=0, le=100, description="表显里程(万公里)")
    transfer_times: int = Field(0, ge=0, le=20, description="过户次数")
    city: str = Field(..., min_length=1, max_length=50, description="所在城市")
    gearbox: str | None = Field(None, max_length=20, description="变速箱")
    fuel_type: str | None = Field(None, max_length=20, description="能源类型")
    displacement_l: float | None = Field(None, ge=0, le=10, description="排量(L)")
    guide_price_wan: float | None = Field(None, ge=0, le=2000, description="新车指导价(万元)")
    contact: str | None = Field(None, max_length=50, description="提交人")

    @field_validator("brand", "series", "model_name", "city")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("不能为空")
        return value

    @field_validator("gearbox", "fuel_type", "contact")
    @classmethod
    def _blank_to_none(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None

    @field_validator("reg_date")
    @classmethod
    def _sane_reg_date(cls, value: date | None) -> date | None:
        if value is None:
            return None
        if value > date.today():
            raise ValueError("上牌时间不能晚于今天")
        if value.year < MIN_YEAR:
            raise ValueError(f"上牌时间早于 {MIN_YEAR} 年, 请检查")
        return value


class CarCreate(CarBase):
    """新增。"""


class CarUpdate(BaseModel):
    """修改: 所有字段可选, 只改传上来的那些。"""

    brand: str | None = Field(None, min_length=1, max_length=50)
    series: str | None = Field(None, min_length=1, max_length=80)
    model_name: str | None = Field(None, min_length=1, max_length=120)
    reg_date: date | None = None
    mileage_wan: float | None = Field(None, ge=0, le=100)
    transfer_times: int | None = Field(None, ge=0, le=20)
    city: str | None = Field(None, min_length=1, max_length=50)
    gearbox: str | None = Field(None, max_length=20)
    fuel_type: str | None = Field(None, max_length=20)
    displacement_l: float | None = Field(None, ge=0, le=10)
    guide_price_wan: float | None = Field(None, ge=0, le=2000)
    contact: str | None = Field(None, max_length=50)


class CarOut(CarBase):
    """输出: 在输入参数基础上补上主键与时间戳。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime


class CarListOut(BaseModel):
    total: int
    items: list[CarOut]


class HealthOut(BaseModel):
    status: str
    app: str
    version: str


class DbHealthOut(BaseModel):
    status: str
    database: str
