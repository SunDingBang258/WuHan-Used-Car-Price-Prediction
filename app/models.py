"""ORM 模型: 用户提交的二手车参数。

前 8 个字段是用户填的; 后面 5 个是后台按 品牌/车系 查 app/reference.json 得到的,
正好对应价格预测模型要用的特征(见 data/prepare_dataset.py 的 FEATURES)。
"""
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class Car(Base):
    """一条待估价的二手车参数记录。"""

    __tablename__ = "cars"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # --- 用户填的 ---
    brand: Mapped[str] = mapped_column(String(50), nullable=False, index=True, comment="品牌")
    series: Mapped[str] = mapped_column(String(80), nullable=False, index=True, comment="车系")
    car_age_years: Mapped[float] = mapped_column(Numeric(4, 1), nullable=False, comment="车龄(年)")
    mileage_wan: Mapped[float] = mapped_column(
        Numeric(6, 2), nullable=False, comment="表显里程(万公里)"
    )
    zero_transfer: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, comment="0次过户"
    )
    factory_warranty: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, comment="原厂质保"
    )
    near_new: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, comment="准新车"
    )

    # --- 后台查表补的 ---
    brand_id: Mapped[str] = mapped_column(String(20), nullable=False, index=True, comment="品牌ID")
    series_id: Mapped[str] = mapped_column(String(20), nullable=False, index=True, comment="车系ID")
    brand_discount_median: Mapped[float | None] = mapped_column(
        Numeric(5, 2), nullable=True, comment="品牌平均折价率(%)"
    )
    series_discount_median: Mapped[float | None] = mapped_column(
        Numeric(5, 2), nullable=True, comment="车系平均折价率(%)"
    )
    series_price_median: Mapped[float | None] = mapped_column(
        Numeric(8, 2), nullable=True, comment="车系历史中位价(万元)"
    )

    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=_utcnow, onupdate=_utcnow
    )

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return f"<Car id={self.id} {self.brand} {self.series} {self.model_name}>"
