"""请求 / 响应的数据结构与校验规则。"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class CarInput(BaseModel):
    """用户填的参数。品牌/车系填名称, 后台会查表换成 ID 与统计特征。"""

    brand: str = Field(..., min_length=1, max_length=50, description="品牌")
    series: str = Field(..., min_length=1, max_length=80, description="车系")
    car_age_years: float = Field(..., ge=0, le=50, description="车龄(年)")
    mileage_wan: float = Field(..., ge=0, le=100, description="表显里程(万公里)")
    zero_transfer: bool = Field(False, description="0次过户")
    factory_warranty: bool = Field(False, description="原厂质保")
    near_new: bool = Field(False, description="准新车")

    @field_validator("brand", "series")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("不能为空")
        return value


class CarCreate(CarInput):
    """新增请求体: 与用户输入一致, 查表字段由后台补。"""


class CarUpdate(BaseModel):
    """修改: 字段都可选, 只改传上来的那些。品牌与车系必须一起改。"""

    brand: str | None = Field(None, min_length=1, max_length=50)
    series: str | None = Field(None, min_length=1, max_length=80)
    car_age_years: float | None = Field(None, ge=0, le=50)
    mileage_wan: float | None = Field(None, ge=0, le=100)
    zero_transfer: bool | None = None
    factory_warranty: bool | None = None
    near_new: bool | None = None


class CarOut(CarInput):
    """输出: 用户输入 + 查表得到的特征 + 主键与时间戳。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    brand_id: str
    series_id: str
    brand_discount_median: float | None
    series_discount_median: float | None
    series_price_median: float | None
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
