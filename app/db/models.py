from datetime import date

from geoalchemy2 import Geometry
from sqlalchemy import Date, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class StopRecord(Base):
    __tablename__ = "stops"

    id: Mapped[str] = mapped_column(String(120), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    mode: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    location: Mapped[object] = mapped_column(Geometry("POINT", srid=4326), nullable=False)


class SegmentRecord(Base):
    __tablename__ = "segments"

    id: Mapped[str] = mapped_column(String(120), primary_key=True)
    route_id: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    route_code: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    route_name: Mapped[str] = mapped_column(String(255), nullable=False)
    from_stop_id: Mapped[str] = mapped_column(ForeignKey("stops.id"), nullable=False, index=True)
    to_stop_id: Mapped[str] = mapped_column(ForeignKey("stops.id"), nullable=False, index=True)
    mode: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    service_category: Mapped[str] = mapped_column(String(32), nullable=False)
    service_name: Mapped[str] = mapped_column(String(255), nullable=False)
    avg_duration_min: Mapped[float] = mapped_column(Float, nullable=False)
    fare: Mapped[int] = mapped_column(Integer, nullable=False)
    fare_product_id: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    data_confidence: Mapped[str] = mapped_column(String(16), nullable=False)
    last_verified_at: Mapped[date] = mapped_column(Date, nullable=False)
    color: Mapped[str] = mapped_column(String(6), nullable=False)
    geometry: Mapped[object] = mapped_column(Geometry("LINESTRING", srid=4326), nullable=False)
    walking_distance_meters: Mapped[float | None] = mapped_column(Float, nullable=True)
    walking_route_source: Mapped[str | None] = mapped_column(String(16), nullable=True)
