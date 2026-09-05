import pandas as pd
import os
from typing import List, Dict, Optional
from datetime import datetime
from app.services.excel_ingest import parse_sheet


DEFAULT_EXCEL = os.path.join(os.path.dirname(os.path.dirname(__file__)), "..", "data", "excel", "combined_co2_data_only_file.xls")
DEFAULT_EXCEL = os.path.abspath(DEFAULT_EXCEL)


def _read_all(file_path: Optional[str] = None) -> List[Dict]:
    path = file_path or DEFAULT_EXCEL
    if not os.path.exists(path):
        return []
    xls = pd.read_excel(path, sheet_name=None)
    all_recs = []
    for sheet, df in xls.items():
        try:
            recs = parse_sheet(df)
            all_recs.extend(recs)
        except Exception:
            continue
    return all_recs


def get_measurements(file_path: Optional[str] = None, well: Optional[str] = None, start: Optional[datetime] = None, end: Optional[datetime] = None) -> List[Dict]:
    recs = _read_all(file_path)
    if well:
        recs = [r for r in recs if str(r.get("well_name")).lower() == str(well).lower()]
    if start:
        recs = [r for r in recs if r.get("timestamp") >= start]
    if end:
        recs = [r for r in recs if r.get("timestamp") <= end]
    return recs
