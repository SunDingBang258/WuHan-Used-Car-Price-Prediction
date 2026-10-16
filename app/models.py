"""ORM 模型: 用户提交的二手车参数。

这些字段就是后续喂给价格预测模型的特征, 所以刻意与爬虫抓取的维度对齐
(见 data/爬虫/README.md 里的 8 个维度)。
"""
from __future__ import annotations

from datetime import UTC, date, datetime

from sqlalchemy import Date, DateTime, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class Car(Base):
    """一条待估价的二手车参数记录。"""

    __tablename__ = "cars"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    brand: Mapped[str] = mapped_column(String(50), nullable=False, index=True, comment="品牌")
    series: Mapped[str] = mapped_column(String(80), nullable=False, index=True, comment="车系")
    model_name: Mapped[str] = mapped_column(String(120), nullable=False, comment="车型")
    reg_date: Mapped[date | None] = mapped_column(Date, nullable=True, comment="上牌时间")
    mileage_wan: Mapped[float] = mapped_column(Numeric(6, 2), nullable=False, comment="表显里程(万公里)")
    transfer_times: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment="过户次数")
    city: Mapped[str] = mapped_column(String(50), nullable=False, index=True, comment="所在城市")
    gearbox: Mapped[str | None] = mapped_column(String(20), nullable=True, comment="变速箱")
    fuel_type: Mapped[str | None] = mapped_column(String(20), nullable=True, comment="能源类型")
    displacement_l: Mapped[float | None] = mapped_column(Numeric(3, 1), nullable=True, comment="排量(L)")
    guide_price_wan: Mapped[float | None] = mapped_column(
        Numeric(8, 2), nullable=True, comment="新车指导价(万元)"
    )
    contact: Mapped[str | None] = mapped_column(String(50), nullable=True, comment="提交人")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=_utcnow, onupdate=_utcnow
    )

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return f"<Car id={self.id} {self.brand} {self.series} {self.model_name}>"
