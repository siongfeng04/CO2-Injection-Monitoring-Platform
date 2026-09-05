import pandas as pd
from typing import List
from sklearn.ensemble import IsolationForest
import numpy as np
import joblib
from datetime import datetime


def compute_kpis(measurements: List[dict]):
    df = pd.DataFrame(measurements)
    if df.empty:
        return {}
    df = df.sort_values("timestamp")
    res = {
        "bhp_latest": float(df["bhp"].dropna().iloc[-1]) if not df["bhp"].dropna().empty else None,
        "bht_latest": float(df["bht"].dropna().iloc[-1]) if not df["bht"].dropna().empty else None,
        "injection_rate_latest": float(df["injection_rate"].dropna().iloc[-1]) if not df["injection_rate"].dropna().empty else None,
        "daily_injected_sum": float(df["daily_injected"].dropna().sum()) if "daily_injected" in df else None,
        "cumulative_co2_latest": float(df["cumulative_co2"].dropna().iloc[-1]) if "cumulative_co2" in df and not df["cumulative_co2"].dropna().empty else None,
    }
    return res


def detect_anomalies(measurements: List[dict], features=("bhp","injection_rate")):
    df = pd.DataFrame(measurements)
    if df.empty:
        return []
    feat_df = df[list(features)].fillna(0)
    clf = IsolationForest(contamination=0.01, random_state=42)
    preds = clf.fit_predict(feat_df)
    df["anomaly"] = (preds == -1).astype(int)
    return df[["timestamp"] + list(features) + ["anomaly"]].to_dict(orient="records")


def save_model(obj, path: str):
    joblib.dump(obj, path)


def load_model(path: str):
    return joblib.load(path)
