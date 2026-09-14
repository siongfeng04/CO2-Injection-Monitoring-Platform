from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy.orm import Session

from app import models

DEFAULT_FULL_DATA = (
    Path(__file__).resolve().parents[2]
    / "data"
    / "excel"
    / "combined_co2_data_only_file.xls"
)

FULL_DATA_COLUMNS = {
    "Date": "injection_date",
    "Time": "injection_time",
    "Date & Time": "timestamp",
    "Bottom Hole Pressure": "bhp",
    "Corrected Bottom Hole Pressure": "corrected_bhp",
    "Bottom Hole Temperature": "bht",
    "Surface Temperature": "surface_temp",
    "Surface PSI": "surface_psi",
    "Annulus PSI": "annulus_psi",
    "Flowrate meter": "flowrate_meter",
    "Pump Speed": "pump_speed",
    "Calc. Flow from Pump Speed": "calc_flow_from_pump_speed",
    "Flow BPM": "flow_bpm",
    "Temperature before Triplex": "temperature_before_triplex",
    "Pressure before Triplex": "pressure_before_triplex",
}


def read_full_data(file_path: str | Path = DEFAULT_FULL_DATA) -> pd.DataFrame:
    frame = pd.read_excel(file_path, sheet_name="Full", engine="xlrd")
    missing = set(FULL_DATA_COLUMNS) - set(frame.columns)
    if missing:
        raise ValueError(f"Full sheet is missing columns: {', '.join(sorted(missing))}")
    return frame.rename(columns=FULL_DATA_COLUMNS)


def _optional_float(value: Any) -> float | None:
    numeric = pd.to_numeric(value, errors="coerce")
    if pd.isna(numeric):
        return None
    return float(numeric)


def import_full_data(
    db: Session, file_path: str | Path = DEFAULT_FULL_DATA, replace: bool = True
) -> int:
    frame = read_full_data(file_path)
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], errors="coerce")
    frame = frame.dropna(subset=["timestamp"]).sort_values("timestamp")
    if replace:
        db.query(models.FullData).delete()

    records = []
    for row in frame.itertuples(index=False):
        values = row._asdict()
        timestamp = values["timestamp"].to_pydatetime()
        records.append(
            models.FullData(
                timestamp=timestamp,
                injection_date=timestamp.date(),
                injection_time=timestamp.time(),
                surface_temp=_optional_float(values["surface_temp"]),
                surface_psi=_optional_float(values["surface_psi"]),
                annulus_psi=_optional_float(values["annulus_psi"]),
                flowrate_meter=_optional_float(values["flowrate_meter"]),
                pump_speed=_optional_float(values["pump_speed"]),
                calc_flow_from_pump_speed=_optional_float(values["calc_flow_from_pump_speed"]),
                flow_bpm=_optional_float(values["flow_bpm"]),
                temperature_before_triplex=_optional_float(values["temperature_before_triplex"]),
                pressure_before_triplex=_optional_float(values["pressure_before_triplex"]),
                bhp=_optional_float(values["bhp"]),
                corrected_bhp=_optional_float(values["corrected_bhp"]),
                bht=_optional_float(values["bht"]),
            )
        )

    db.bulk_save_objects(records)
    db.commit()
    return len(records)


def full_data_rows(db: Session) -> list[dict[str, Any]]:
    rows = db.query(models.FullData).order_by(models.FullData.timestamp).all()
    return [
        {
            "timestamp": row.timestamp,
            "bhp": row.bhp,
            "corrected_bhp": row.corrected_bhp,
            "bht": row.bht,
            "surface_temp": row.surface_temp,
            "surface_psi": row.surface_psi,
            "annulus_psi": row.annulus_psi,
            "flowrate_meter": row.flowrate_meter,
            "pump_speed": row.pump_speed,
            "calc_flow_from_pump_speed": row.calc_flow_from_pump_speed,
            "flow_bpm": row.flow_bpm,
            "temperature_before_triplex": row.temperature_before_triplex,
            "pressure_before_triplex": row.pressure_before_triplex,
        }
        for row in rows
    ]


def latest_operating_conditions(db: Session) -> dict[str, Any] | None:
    required_fields = [
        models.FullData.surface_psi,
        models.FullData.annulus_psi,
        models.FullData.pump_speed,
        models.FullData.surface_temp,
        models.FullData.temperature_before_triplex,
        models.FullData.pressure_before_triplex,
    ]
    query = db.query(models.FullData)
    for field in required_fields:
        query = query.filter(field.isnot(None), field != 0)
    row = query.order_by(models.FullData.timestamp.desc()).first()
    if row is None:
        return None
    return {
        "timestamp": row.timestamp.isoformat() if row.timestamp else None,
        "surface_psi": row.surface_psi,
        "annulus_psi": row.annulus_psi,
        "pump_speed": row.pump_speed,
        "surface_temp": row.surface_temp,
        "temperature_before_triplex": row.temperature_before_triplex,
        "pressure_before_triplex": row.pressure_before_triplex,
    }
