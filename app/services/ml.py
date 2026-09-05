import os
import numpy as np
import pandas as pd
from sklearn.metrics import mean_squared_error, mean_absolute_error, r2_score
from xgboost import XGBRegressor
import joblib
from datetime import datetime, timedelta
from typing import List, Dict

from app.crud import query_measurements
import re


MODELS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "models")
os.makedirs(MODELS_DIR, exist_ok=True)


def _prepare_df(measurements: List[dict]):
    df = pd.DataFrame(measurements)
    if df.empty:
        return df
    df = df.sort_values("timestamp")
    df["timestamp"] = pd.to_datetime(df["timestamp"]) if not np.issubdtype(df["timestamp"].dtype, np.datetime64) else df["timestamp"]
    df["ts_epoch"] = df["timestamp"].astype('int64') // 10 ** 9
    # fill numeric NaNs with 0 for training simplicity
    for c in ["injection_rate", "bht", "annulus_pressure", "pump_speed", "bhp"]:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors='coerce').fillna(0)
        else:
            df[c] = 0
    return df


def train_pressure_model(db, well_id: int, model_name: str = None):
    # fetch all measurements for well
    meas = query_measurements(db, well_id, datetime(1970,1,1), datetime.now())
    records = [
        {
            "timestamp": m.timestamp,
            "bhp": m.bhp,
            "bht": m.bht,
            "injection_rate": m.injection_rate,
            "annulus_pressure": m.annulus_pressure,
            "pump_speed": m.pump_speed,
        }
        for m in meas
    ]
    df = _prepare_df(records)
    if df.shape[0] < 10:
        raise ValueError("Not enough data to train model (need >=10 rows)")

    features = ["ts_epoch", "injection_rate", "bht", "annulus_pressure", "pump_speed"]
    X = df[features].values
    y = df["bhp"].values

    # simple train/test split
    split = int(0.8 * len(df))
    X_train, X_test = X[:split], X[split:]
    y_train, y_test = y[:split], y[split:]

    model = XGBRegressor(n_estimators=100, max_depth=4, random_state=42)
    model.fit(X_train, y_train)

    preds = model.predict(X_test)
    metrics = {
        "rmse": float(np.sqrt(mean_squared_error(y_test, preds))),
        "mae": float(mean_absolute_error(y_test, preds)),
        "r2": float(r2_score(y_test, preds)),
    }

    if model_name is None:
        model_name = f"pressure_well_{well_id}.joblib"

    path = os.path.join(MODELS_DIR, model_name)
    joblib.dump({"model": model, "features": features}, path)

    return {"metrics": metrics, "model_path": path}


def load_model_for_well(well_id: int):
    path = os.path.join(MODELS_DIR, f"pressure_well_{well_id}.joblib")
    if not os.path.exists(path):
        return None
    return joblib.load(path)


def _sanitize_key(key: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_\-]", "_", key.lower())


def train_pressure_from_records(records: List[dict], model_key: str = None):
    df = _prepare_df(records)
    if df.shape[0] < 10:
        raise ValueError("Not enough data to train model (need >=10 rows)")
    features = ["ts_epoch", "injection_rate", "bht", "annulus_pressure", "pump_speed"]
    X = df[features].values
    y = df["bhp"].values
    split = int(0.8 * len(df))
    X_train, X_test = X[:split], X[split:]
    y_train, y_test = y[:split], y[split:]
    model = XGBRegressor(n_estimators=100, max_depth=4, random_state=42)
    model.fit(X_train, y_train)
    preds = model.predict(X_test)
    metrics = {
        "rmse": float(np.sqrt(mean_squared_error(y_test, preds))),
        "mae": float(mean_absolute_error(y_test, preds)),
        "r2": float(r2_score(y_test, preds)),
    }
    if model_key is None:
        model_key = "default"
    safe = _sanitize_key(model_key)
    model_name = f"pressure_well_{safe}.joblib"
    path = os.path.join(MODELS_DIR, model_name)
    joblib.dump({"model": model, "features": features, "model_key": model_key}, path)
    return {"metrics": metrics, "model_path": path}


def load_model_by_key(model_key: str):
    safe = _sanitize_key(model_key)
    path = os.path.join(MODELS_DIR, f"pressure_well_{safe}.joblib")
    if not os.path.exists(path):
        return None
    return joblib.load(path)


def predict_with_model_key(start: datetime, days: int = 7, injection_rate: float = None, model_key: str = None):
    pkg = load_model_by_key(model_key)
    if pkg is None:
        raise FileNotFoundError("Model not found for key")
    model = pkg["model"]
    rows = []
    for d in range(days):
        ts = start + timedelta(days=d)
        rows.append({
            "timestamp": ts,
            "ts_epoch": int(ts.timestamp()),
            "injection_rate": injection_rate if injection_rate is not None else 0,
            "bht": 0,
            "annulus_pressure": 0,
            "pump_speed": 0,
        })
    df = pd.DataFrame(rows)
    X = df[["ts_epoch", "injection_rate", "bht", "annulus_pressure", "pump_speed"]].values
    preds = model.predict(X)
    out = []
    for i, p in enumerate(preds):
        out.append({"timestamp": df.loc[i, "timestamp"].isoformat(), "predicted_bhp": float(p)})
    return out


def simulate_with_model_key(schedule: List[Dict], model_key: str = None):
    pkg = load_model_by_key(model_key)
    if pkg is None:
        raise FileNotFoundError("Model not found for key")
    model = pkg["model"]
    rows = []
    for item in schedule:
        ts = pd.to_datetime(item.get("date"))
        rows.append({
            "timestamp": ts,
            "ts_epoch": int(ts.timestamp()),
            "injection_rate": float(item.get("injection_rate", 0)),
            "bht": 0,
            "annulus_pressure": 0,
            "pump_speed": 0,
        })
    df = pd.DataFrame(rows).sort_values("timestamp")
    X = df[["ts_epoch", "injection_rate", "bht", "annulus_pressure", "pump_speed"]].values
    preds = model.predict(X)
    out = []
    for i, p in enumerate(preds):
        out.append({"timestamp": df.iloc[i]["timestamp"].isoformat(), "predicted_bhp": float(p), "injection_rate": float(df.iloc[i]["injection_rate"])})
    return out


def predict_pressure(db, well_id: int, start: datetime, days: int = 7, injection_rate: float = None):
    # load model
    pkg = load_model_for_well(well_id)
    if pkg is None:
        raise FileNotFoundError("Model not found for well")
    model = pkg["model"]
    features = pkg["features"]

    # build future dataframe daily
    rows = []
    for d in range(days):
        ts = start + timedelta(days=d)
        rows.append({
            "timestamp": ts,
            "ts_epoch": int(ts.timestamp()),
            "injection_rate": injection_rate if injection_rate is not None else 0,
            "bht": 0,
            "annulus_pressure": 0,
            "pump_speed": 0,
        })
    df = pd.DataFrame(rows)
    X = df[["ts_epoch", "injection_rate", "bht", "annulus_pressure", "pump_speed"]].values
    preds = model.predict(X)
    out = []
    for i, p in enumerate(preds):
        out.append({"timestamp": df.loc[i, "timestamp"].isoformat(), "predicted_bhp": float(p)})
    return out


def simulate_whatif(db, well_id: int, start: datetime, schedule: List[Dict]):
    # schedule: list of {"date": ISO, "injection_rate": float}
    pkg = load_model_for_well(well_id)
    if pkg is None:
        raise FileNotFoundError("Model not found for well")
    model = pkg["model"]

    rows = []
    for item in schedule:
        ts = pd.to_datetime(item.get("date"))
        rows.append({
            "timestamp": ts,
            "ts_epoch": int(ts.timestamp()),
            "injection_rate": float(item.get("injection_rate", 0)),
            "bht": 0,
            "annulus_pressure": 0,
            "pump_speed": 0,
        })
    df = pd.DataFrame(rows).sort_values("timestamp")
    X = df[["ts_epoch", "injection_rate", "bht", "annulus_pressure", "pump_speed"]].values
    preds = model.predict(X)
    out = []
    for i, p in enumerate(preds):
        out.append({"timestamp": df.iloc[i]["timestamp"].isoformat(), "predicted_bhp": float(p), "injection_rate": float(df.iloc[i]["injection_rate"])})
    return out
