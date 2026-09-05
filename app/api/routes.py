from fastapi import APIRouter, UploadFile, File, Depends, HTTPException
from app.database import get_db, engine
from sqlalchemy.orm import Session
from app.services.excel_ingest import ingest_excel
from app import models
from app.crud import (
    get_dashboard_measurements,
    get_full_data,
    get_full_data_range,
    get_subset_flow,
    get_subset_data,
    query_measurements,
)
from app.services.analysis import compute_kpis, detect_anomalies
from app.services import excel_source
import tempfile
from fastapi.responses import JSONResponse
from datetime import datetime
from sqlalchemy import text

router = APIRouter()


@router.get("/")
def root():
    return {"message": "CCS Digital Twin API", "docs": "/docs"}


@router.get("/health")
def health(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))
    return {"status": "ok", "database": "connected"}


def _full_data_row(row):
    return {
        "timestamp": row.timestamp.isoformat() if row.timestamp else None,
        "surface_temp": row.surface_temp,
        "surface_psi": row.surface_psi,
        "annulus_psi": row.annulus_psi,
        "injection_rate": None,
        "pump_speed": row.pump_speed,
        "bhp": row.bhp,
        "corrected_bottom_hole_pressure": row.corrected_bhp,
        "bht": row.bht,
        "bottom_hole_temperature": row.bht,
    }


def _subset_data_row(row):
    return {
        "date_time": row.timestamp.isoformat() if row.timestamp else None,
        "surface_temperature": row.surface_temp,
        "surface_psi": row.surface_psi,
        "annulus_psi": row.annulus_psi,
        "pump_speed": row.pump_speed,
        "flow_bpm": row.flow_bpm,
        "flow_gpm": row.flow_gpm,
    }


@router.get("/data/fulldata")
def list_full_data(limit: int = 10, db: Session = Depends(get_db)):
    return {"data": [_full_data_row(row) for row in get_full_data(db, limit)]}


@router.get("/data/subset-data")
def list_subset_data(limit: int = 10, db: Session = Depends(get_db)):
    return {"data": [_subset_data_row(row) for row in get_subset_data(db, limit)]}


@router.get("/dashboard/subset-flow")
def subset_flow(start: str, end: str, db: Session = Depends(get_db)):
    try:
        start_dt = datetime.fromisoformat(start)
        end_dt = datetime.fromisoformat(end)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="start and end must be ISO timestamps") from exc

    if end_dt < start_dt:
        raise HTTPException(status_code=400, detail="end must be after start")

    rows = get_subset_flow(db, start_dt, end_dt)
    return {
        "source": "subset_data",
        "data": [
            {
                "date_time": row.timestamp.isoformat() if row.timestamp else None,
                "flow_bpm": row.flow_bpm,
                "flow_gpm": row.flow_gpm,
                "surface_psi": row.surface_psi,
                "surface_temperature": row.surface_temp,
            }
            for row in rows
        ],
    }


@router.get("/dashboard/metrics")
def dashboard_metrics(
    start: str,
    end: str,
    db: Session = Depends(get_db),
):
    try:
        start_dt = datetime.fromisoformat(start)
        end_dt = datetime.fromisoformat(end)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="start and end must be ISO timestamps") from exc

    if end_dt < start_dt:
        raise HTTPException(status_code=400, detail="end must be after start")

    rows = get_dashboard_measurements(db, start_dt, end_dt)
    data = [_full_data_row(row) for row in rows]
    latest = data[-1] if data else None
    return {
        "source": "fulldata",
        "row_count": len(data),
        "latest_timestamp": latest["timestamp"] if latest else None,
        "kpis": compute_kpis(data),
        "timeseries": data,
    }


@router.get("/wells")
def list_wells(use_excel: bool = True, db: Session = Depends(get_db)):
    if use_excel:
        recs = excel_source.get_measurements()
        names = sorted({r.get("well_name") for r in recs if r.get("well_name")})
        return {"wells": names}
    ws = db.query(models.Well).all()
    return {"wells": [w.name for w in ws]}


@router.post("/ingest-excel")
def ingest_excel_endpoint(file: UploadFile = File(...), db: Session = Depends(get_db)):
    suffix = ".xlsx" if file.filename.endswith("x") else ""
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=True) as tmp:
        content = file.file.read()
        tmp.write(content)
        tmp.flush()
        inserted = ingest_excel(tmp.name, db)
    return {"inserted": inserted}


@router.get("/metrics/injection")
def metrics_injection(start: str, end: str, well: str = None, use_excel: bool = True, db: Session = Depends(get_db)):
    try:
        start_dt = datetime.fromisoformat(start)
        end_dt = datetime.fromisoformat(end)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid date format. Use ISO format.")

    if use_excel:
        records = excel_source.get_measurements(well=well, start=start_dt, end=end_dt)
        data = [
            {
                "timestamp": r.get("timestamp").isoformat(),
                "bhp": r.get("bhp"),
                "bht": r.get("bht"),
                "injection_rate": r.get("injection_rate"),
                "pump_speed": r.get("pump_speed"),
                "annulus_pressure": r.get("annulus_pressure"),
            }
            for r in records
        ]
    else:
        if well:
            w = db.query(models.Well).filter(models.Well.name == well).first()
            if not w:
                raise HTTPException(status_code=404, detail="Well not found")
            meas = query_measurements(db, w.id, start_dt, end_dt)
        else:
            meas = db.query(models.Measurement).filter(models.Measurement.timestamp >= start_dt).filter(models.Measurement.timestamp <= end_dt).all()

        data = [
            {
                "timestamp": m.timestamp.isoformat(),
                "bhp": m.bhp,
                "bht": m.bht,
                "injection_rate": m.injection_rate,
                "pump_speed": m.pump_speed,
                "annulus_pressure": m.annulus_pressure,
            }
            for m in meas
        ]
    kpis = compute_kpis(data)
    return {"kpis": kpis, "timeseries": data}


@router.get("/anomalies")
def anomalies(start: str, end: str, well: str = None, use_excel: bool = True, db: Session = Depends(get_db)):
    try:
        start_dt = datetime.fromisoformat(start)
        end_dt = datetime.fromisoformat(end)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid date format. Use ISO format.")

    if use_excel:
        records = excel_source.get_measurements(well=well, start=start_dt, end=end_dt)
        data = [
            {"timestamp": r.get("timestamp"), "bhp": r.get("bhp"), "injection_rate": r.get("injection_rate")} for r in records
        ]
    else:
        if well:
            w = db.query(models.Well).filter(models.Well.name == well).first()
            if not w:
                raise HTTPException(status_code=404, detail="Well not found")
            meas = query_measurements(db, w.id, start_dt, end_dt)
        else:
            meas = db.query(models.Measurement).filter(models.Measurement.timestamp >= start_dt).filter(models.Measurement.timestamp <= end_dt).all()

        data = [
            {"timestamp": m.timestamp, "bhp": m.bhp, "injection_rate": m.injection_rate} for m in meas
        ]
    anomalies = detect_anomalies(data)
    return JSONResponse(content={"anomalies": anomalies})


from app.services import ml


@router.post("/train-pressure")
def train_pressure(well: str, use_excel: bool = True, db: Session = Depends(get_db)):
    if use_excel:
        # load records from excel
        records = excel_source.get_measurements(well=well)
        if not records:
            raise HTTPException(status_code=404, detail="No records found in excel for well")
        try:
            res = ml.train_pressure_from_records(records, model_key=well)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        return res
    w = db.query(models.Well).filter(models.Well.name == well).first()
    if not w:
        raise HTTPException(status_code=404, detail="Well not found")
    try:
        res = ml.train_pressure_model(db, w.id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return res


@router.get("/predict-pressure")
def predict_pressure(well: str, start: str, days: int = 7, injection_rate: float = None, use_excel: bool = True, db: Session = Depends(get_db)):
    try:
        start_dt = datetime.fromisoformat(start)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid date format")
    if use_excel:
        try:
            out = ml.predict_with_model_key(start_dt, days=days, injection_rate=injection_rate, model_key=well)
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="Model not found; train first")
        return {"predictions": out}
    w = db.query(models.Well).filter(models.Well.name == well).first()
    if not w:
        raise HTTPException(status_code=404, detail="Well not found")
    try:
        out = ml.predict_pressure(db, w.id, start_dt, days=days, injection_rate=injection_rate)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Model not found; train first")
    return {"predictions": out}


@router.post("/simulate-whatif")
def simulate_whatif(payload: dict, use_excel: bool = True, db: Session = Depends(get_db)):
    well = payload.get("well")
    schedule = payload.get("schedule", [])
    if not well:
        raise HTTPException(status_code=400, detail="well required")
    if use_excel:
        try:
            out = ml.simulate_with_model_key(schedule, model_key=well)
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="Model not found; train first")
        return {"simulation": out}
    w = db.query(models.Well).filter(models.Well.name == well).first()
    if not w:
        raise HTTPException(status_code=404, detail="Well not found")
    try:
        out = ml.simulate_whatif(db, w.id, None, schedule)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Model not found; train first")
    return {"simulation": out}
