import pandas as pd
from datetime import datetime
from typing import List, Dict
from app.crud import get_or_create_well, bulk_insert_measurements


EXPECTED_COLUMNS = {
    "date": ["date", "timestamp", "time"],
    "well": ["well", "well_name", "well id"],
    "bhp": ["bhp", "bottom hole pressure"],
    "bht": ["bht", "bottom hole temperature"],
    "injection_rate": ["injection_rate", "injection rate"],
    "daily_injected": ["daily_injected", "daily injected"],
    "cumulative_co2": ["cumulative_co2", "cumulative"] ,
    "annulus_pressure": ["annulus_pressure", "annulus pressure"],
    "pump_speed": ["pump_speed", "pump speed"],
}


def _normalize_col(col: str) -> str:
    return col.strip().lower()


def parse_sheet(df: pd.DataFrame) -> List[Dict]:
    cols = { _normalize_col(c): c for c in df.columns }
    # map expected
    mapped = {}
    for key, options in EXPECTED_COLUMNS.items():
        for o in options:
            if o in cols:
                mapped[key] = cols[o]
                break

    records = []
    for _, row in df.iterrows():
        try:
            ts = row.get(mapped.get("date"))
            if pd.isna(ts):
                continue
            if not isinstance(ts, pd.Timestamp):
                ts = pd.to_datetime(ts)

            well = row.get(mapped.get("well")) or "default"

            rec = {
                "timestamp": ts.to_pydatetime(),
                "bhp": float(row.get(mapped.get("bhp"))) if mapped.get("bhp") in row and not pd.isna(row.get(mapped.get("bhp"))) else None,
                "bht": float(row.get(mapped.get("bht"))) if mapped.get("bht") in row and not pd.isna(row.get(mapped.get("bht"))) else None,
                "injection_rate": float(row.get(mapped.get("injection_rate"))) if mapped.get("injection_rate") in row and not pd.isna(row.get(mapped.get("injection_rate"))) else None,
                "daily_injected": float(row.get(mapped.get("daily_injected"))) if mapped.get("daily_injected") in row and not pd.isna(row.get(mapped.get("daily_injected"))) else None,
                "cumulative_co2": float(row.get(mapped.get("cumulative_co2"))) if mapped.get("cumulative_co2") in row and not pd.isna(row.get(mapped.get("cumulative_co2"))) else None,
                "annulus_pressure": float(row.get(mapped.get("annulus_pressure"))) if mapped.get("annulus_pressure") in row and not pd.isna(row.get(mapped.get("annulus_pressure"))) else None,
                "pump_speed": float(row.get(mapped.get("pump_speed"))) if mapped.get("pump_speed") in row and not pd.isna(row.get(mapped.get("pump_speed"))) else None,
                "well_name": str(well),
            }
            records.append(rec)
        except Exception:
            continue

    return records


def ingest_excel(file_path: str, db):
    xls = pd.read_excel(file_path, sheet_name=None)
    total = 0
    for sheet_name, df in xls.items():
        records = parse_sheet(df)
        if not records:
            continue
        # ensure well exists and set well_id
        measurements = []
        for r in records:
            well = get_or_create_well(db, r.pop("well_name"))
            m = r.copy()
            m["well_id"] = well.id
            measurements.append(m)

        bulk_insert_measurements(db, measurements)
        total += len(measurements)

    return total
