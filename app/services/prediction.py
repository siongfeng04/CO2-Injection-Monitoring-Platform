from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingRegressor, RandomForestRegressor
from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

from app.services.fulldata import full_data_rows

RECORDING_PERIODS = [
    ("2009-09-20 07:34:53", "2009-09-20 16:59:15"),
    ("2009-09-21 17:33:11", "2009-09-22 00:58:09"),
    ("2009-09-24 19:40:25", "2009-09-25 07:42:45"),
]
FEATURES = [
    "surface_temp",
    "surface_psi",
    "annulus_psi",
    "flowrate_meter",
    "pump_speed",
    "calc_flow_from_pump_speed",
    "flow_bpm",
    "temperature_before_triplex",
    "pressure_before_triplex",
]
TARGETS = {
    "pressure": ("corrected_bhp", "Corrected Bottom-Hole Pressure"),
    "temperature": ("bht", "Bottom-Hole Temperature"),
}
OPTIMIZATION_FEATURES = {
    "cbhp": [
        "surface_psi",
        "annulus_psi",
        "flow_bpm",
        "pump_speed",
        "temperature_before_triplex",
        "pressure_before_triplex",
    ],
    "bht": ["surface_temp", "flow_bpm", "pump_speed", "surface_psi", "annulus_psi"],
}


def _recording_mask(timestamps: pd.Series) -> pd.Series:
    mask = pd.Series(False, index=timestamps.index)
    for start, end in RECORDING_PERIODS:
        mask |= timestamps.between(pd.Timestamp(start), pd.Timestamp(end))
    return mask


def _prepare_frame(rows: list[dict[str, Any]]) -> pd.DataFrame:
    frame = pd.DataFrame(rows)
    if frame.empty:
        return frame
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], errors="coerce")
    frame = frame.dropna(subset=["timestamp"]).sort_values("timestamp")
    for column in FEATURES + ["bhp", "corrected_bhp", "bht"]:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    active = _recording_mask(frame["timestamp"])
    for column in FEATURES:
        frame.loc[~active, column] = frame.loc[~active, column].fillna(0)
        frame[column] = frame[column].fillna(0)
    for column in ["bhp", "corrected_bhp", "bht"]:
        frame.loc[active, column] = frame.loc[active, column].interpolate(method="linear")
        frame[column] = frame[column].fillna(0)
    return frame.loc[active].copy()


def _metrics(actual: np.ndarray, predicted: np.ndarray) -> dict[str, float]:
    return {
        "mae": float(mean_absolute_error(actual, predicted)),
        "mse": float(mean_squared_error(actual, predicted)),
        "rmse": float(np.sqrt(mean_squared_error(actual, predicted))),
        "r2": float(r2_score(actual, predicted)),
    }


def _fit_target(frame: pd.DataFrame, target: str, label: str) -> dict[str, Any]:
    if len(frame) < 20:
        raise ValueError("At least 20 active fulldata rows are required for prediction")
    x = frame[FEATURES]
    y = frame[target]
    from sklearn.model_selection import train_test_split

    x_train, x_test, y_train, y_test = train_test_split(
        x, y, test_size=0.2, random_state=42
    )
    candidates = {
        "Linear Regression": LinearRegression(),
        "Random Forest Regressor": RandomForestRegressor(
            random_state=42, n_jobs=-1
        ),
        "Gradient Boosting Regressor": GradientBoostingRegressor(random_state=42),
    }
    results = {}
    predictions = {}
    fitted = {}
    for name, model in candidates.items():
        model.fit(x_train, y_train)
        predicted = model.predict(x_test)
        results[name] = _metrics(y_test.to_numpy(), predicted)
        predictions[name] = predicted
        fitted[name] = model

    best_name = max(results, key=lambda name: results[name]["r2"])
    best_model = fitted[best_name]
    best_predicted = predictions[best_name]
    test_frame = pd.DataFrame(
        {
            "timestamp": frame.loc[x_test.index, "timestamp"].dt.strftime(
                "%Y-%m-%dT%H:%M:%S"
            ),
            "actual": y_test.to_numpy(),
            "predicted": best_predicted,
            "residual": y_test.to_numpy() - best_predicted,
        }
    ).sort_values("timestamp")
    importance = None
    if hasattr(best_model, "feature_importances_"):
        importance = best_model.feature_importances_
    else:
        importance = np.abs(best_model.coef_)
    feature_importance = [
        {"feature": feature, "importance": float(value)}
        for feature, value in sorted(
            zip(FEATURES, importance), key=lambda item: item[1], reverse=True
        )
    ]
    return {
        "label": label,
        "best_model": best_name,
        "metrics": results,
        "test_predictions": test_frame.to_dict(orient="records"),
        "feature_importance": feature_importance,
        "row_count": int(len(frame)),
    }


def analyze_fulldata(db) -> dict[str, Any]:
    frame = _prepare_frame(full_data_rows(db))
    if frame.empty:
        raise ValueError("No fulldata rows are available")
    return {
        "source": "fulldata",
        "recording_periods": [
            {"start": start, "end": end} for start, end in RECORDING_PERIODS
        ],
        "row_count": int(len(frame)),
        "pressure": _fit_target(
            frame, TARGETS["pressure"][0], TARGETS["pressure"][1]
        ),
        "temperature": _fit_target(
            frame, TARGETS["temperature"][0], TARGETS["temperature"][1]
        ),
    }


def _fit_optimization_model(frame: pd.DataFrame, target: str, features: list[str]):
    from sklearn.model_selection import train_test_split

    x = frame[features]
    y = frame[target]
    x_train, x_test, y_train, y_test = train_test_split(
        x, y, test_size=0.2, random_state=42
    )
    candidates = {
        "Linear Regression": LinearRegression(),
        "Random Forest Regressor": RandomForestRegressor(random_state=42, n_jobs=-1),
        "Gradient Boosting Regressor": GradientBoostingRegressor(random_state=42),
    }
    scores = {}
    for name, candidate in candidates.items():
        candidate.fit(x_train, y_train)
        scores[name] = r2_score(y_test, candidate.predict(x_test))
    best_name = max(scores, key=scores.get)
    best_model = candidates[best_name].fit(x, y)
    return best_model, best_name


def optimize_injection(db, request: dict[str, Any]) -> dict[str, Any]:
    frame = _prepare_frame(full_data_rows(db))
    if len(frame) < 20:
        raise ValueError("At least 20 active fulldata rows are required for optimization")

    mode = request.get("mode")
    inputs = request.get("inputs", {})
    cbhp_model, cbhp_model_name = _fit_optimization_model(
        frame, "corrected_bhp", OPTIMIZATION_FEATURES["cbhp"]
    )
    bht_model, bht_model_name = _fit_optimization_model(
        frame, "bht", OPTIMIZATION_FEATURES["bht"]
    )

    flow_min = max(0.0, float(request.get("flow_min", 0)))
    flow_max = max(flow_min, float(request.get("flow_max", 100)))
    flow_step = max(0.01, float(request.get("flow_step", 1)))
    flows = np.arange(flow_min, flow_max + flow_step / 2, flow_step)

    def predict(flow):
        cbhp_row = {feature: float(inputs.get(feature, 0)) for feature in OPTIMIZATION_FEATURES["cbhp"]}
        bht_row = {feature: float(inputs.get(feature, 0)) for feature in OPTIMIZATION_FEATURES["bht"]}
        cbhp_row["flow_bpm"] = float(flow)
        bht_row["flow_bpm"] = float(flow)
        cbhp = float(cbhp_model.predict(pd.DataFrame([cbhp_row]))[0])
        bht = float(bht_model.predict(pd.DataFrame([bht_row]))[0])
        return {"flow_bpm": float(flow), "predicted_cbhp": cbhp, "predicted_bht": bht}

    results = [predict(flow) for flow in flows]
    if mode in {"maximum_injection", "safe_operation"}:
        maximum_allowable_cbhp = float(request["cbhp_limit"])
        if mode == "safe_operation":
            safety_margin_pct = float(request.get("safety_margin_pct", 0))
            if not 0 <= safety_margin_pct < 100:
                raise ValueError("Safety margin must be at least 0% and less than 100%")
            limit = maximum_allowable_cbhp * (1 - safety_margin_pct / 100)
        else:
            safety_margin_pct = 0.0
            limit = maximum_allowable_cbhp
        acceptable = [row for row in results if row["predicted_cbhp"] <= limit]
        if not acceptable:
            raise ValueError("No flow rate in the selected search range satisfies the CBHP limit")
        selected = acceptable[-1]
        result = {
            "mode": mode,
            "recommended_flow_bpm": selected["flow_bpm"],
            "predicted_cbhp": selected["predicted_cbhp"],
            "predicted_bht": selected["predicted_bht"],
            "cbhp_limit": limit,
            "models": {"cbhp": cbhp_model_name, "bht": bht_model_name},
        }
        if mode == "safe_operation":
            result.update(
                {
                    "maximum_allowable_cbhp": maximum_allowable_cbhp,
                    "safety_margin_pct": safety_margin_pct,
                    "safe_operating_limit": limit,
                    "remaining_pressure_margin": limit - selected["predicted_cbhp"],
                }
            )
        return result

    if mode == "temperature_control":
        limit = float(request["bht_limit"])
        acceptable = [row for row in results if row["predicted_bht"] <= limit]
        if not acceptable:
            closest = min(results, key=lambda row: row["predicted_bht"])
            return {
                "mode": mode,
                "feasible": False,
                "bht_limit": limit,
                "closest_result": closest,
                "acceptable_results": [],
                "models": {"cbhp": cbhp_model_name, "bht": bht_model_name},
            }
        return {
            "mode": mode,
            "feasible": True,
            "bht_limit": limit,
            "acceptable_flow_min_bpm": acceptable[0]["flow_bpm"],
            "acceptable_flow_max_bpm": acceptable[-1]["flow_bpm"],
            "acceptable_results": acceptable,
            "models": {"cbhp": cbhp_model_name, "bht": bht_model_name},
        }
    raise ValueError("Unsupported optimization mode")
