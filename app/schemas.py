from pydantic import BaseModel
from datetime import datetime
from typing import Optional


class WellBase(BaseModel):
    name: str
    location: Optional[str] = None


class WellCreate(WellBase):
    pass


class Well(WellBase):
    id: int

    class Config:
        orm_mode = True


class MeasurementBase(BaseModel):
    timestamp: datetime
    bhp: Optional[float] = None
    bht: Optional[float] = None
    injection_rate: Optional[float] = None
    daily_injected: Optional[float] = None
    cumulative_co2: Optional[float] = None
    annulus_pressure: Optional[float] = None
    pump_speed: Optional[float] = None


class MeasurementCreate(MeasurementBase):
    well_name: str


class Measurement(MeasurementBase):
    id: int
    well_id: int

    class Config:
        orm_mode = True


class DashboardMetrics(BaseModel):
    source: str
    row_count: int
    latest_timestamp: Optional[datetime] = None
    kpis: dict
    timeseries: list[dict]
