from __future__ import annotations

import threading
from typing import Any

import numpy as np
import pandas as pd
from sklearn.base import clone
from sklearn.ensemble import GradientBoostingRegressor, HistGradientBoostingRegressor, RandomForestRegressor
from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.model_selection import train_test_split

from sqlalchemy import func

from app import models
from app.services.fulldata import full_data_rows

RECORDING_PERIODS = [
    ("2009-09-20 07:34:53", "2009-09-20 16:59:15"),
    ("2009-09-21 17:33:11", "2009-09-22 00:58:09"),
    ("2009-09-24 19:40:25", "2009-09-25 07:42:45"),
]
# Surface measurements as recorded. Pump speed was not logged during the first
# recording period, so its gaps are estimated from flow rate (see _fill_pump_speed).
RAW_FEATURES = [
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
INJECTING_FLOW_BPM = 1.0
ROLLING_WINDOW = "30min"
# Model inputs. Pump speed and calc flow are left out: calc flow is pump speed x 0.0131
# and pump speed follows flow rate (r = 0.98), so they add no information over flow_bpm.
BASE_FEATURES = [
    "surface_temp",
    "surface_psi",
    "annulus_psi",
    "flowrate_meter",
    "flow_bpm",
    "temperature_before_triplex",
    "pressure_before_triplex",
]
# Injection history: bottom-hole conditions depend on how long and how much cold CO2
# has been injected, not only on the instantaneous surface readings.
HISTORY_FEATURES = [
    "injecting",
    "minutes_injecting",
    "minutes_shut_in",
    "injected_volume_bbl",
    "flow_bpm_30min_mean",
    "surface_temp_30min_mean",
    "temperature_before_triplex_30min_mean",
]
FEATURES = BASE_FEATURES + HISTORY_FEATURES
THERMAL_MEMORY_COLUMNS = ["flow_bpm", "surface_temp", "temperature_before_triplex"]
THERMAL_HALFLIVES_MINUTES = [10, 30, 60, 120]
COLD_DOSE_REFERENCE_F = 120.0
THERMAL_FEATURES = [
    f"{column}_ewm{halflife}" for column in THERMAL_MEMORY_COLUMNS for halflife in THERMAL_HALFLIVES_MINUTES
] + ["cold_dose"]
# Thermal memory improved the BHT estimate on unseen periods (mean error 5.36 -> 4.99 °F).
TARGET_FEATURES = {"corrected_bhp": FEATURES, "bht": FEATURES + THERMAL_FEATURES}
# Projection method per target. "held_constant": the surface-data model predicts the next hour
# with the latest operating conditions held constant. "live": models predict the change from the
# latest measured value (BHT: 11-65% more accurate than assuming no change on unseen periods).
PROJECTION_METHOD = {"corrected_bhp": "held_constant", "bht": "live"}
FORECAST_HORIZONS_MINUTES = [10, 30, 60]
LIVE_TREND_MINUTES = [5, 15]
TEST_FRACTION = 0.2

TARGETS = {
    "pressure": ("corrected_bhp", "Corrected Bottom-Hole Pressure"),
    "temperature": ("bht", "Bottom-Hole Temperature"),
}
UNITS = {"corrected_bhp": "psi", "bht": "°F"}
# The optimizer varies flow rate, so it uses instantaneous surface inputs only. Pump speed
# is derived from the searched flow rate (they move together) rather than held fixed.
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
# Two-stage optimizer (CBHP). Stage 1 predicts how the flow-linked surface readings respond to the tested flow;
# stage 2 predicts CBHP from them. Signs give the direction each relationship must follow (monotonic constraints),
# taken from how each reading moves with flow while injecting (surface pressure +0.81, pump-inlet pressure -0.74,
# pump-inlet temperature -0.75, surface temperature +0.48).
OPTIMIZER_STAGE1_INPUTS = ["flow_bpm", "annulus_psi"]
OPTIMIZER_LINKED_RESPONSE = {
    "surface_psi": +1,
    "surface_temp": +1,
    "temperature_before_triplex": -1,
    "pressure_before_triplex": -1,
}
OPTIMIZER_CBHP_MONOTONIC = {"surface_psi": +1, "flow_bpm": +1, "pump_speed": +1}
OPTIMIZER_CBHP_MODEL_NAME = "Two-stage gradient boosting (physics-constrained)"
FORECAST_HORIZON_MINUTES = 60
FORECAST_STEP_MINUTES = 1
# Error bands cover 90% of the absolute errors measured on data the model had not seen.
INTERVAL_QUANTILE = 0.90
# Inputs checked against the range seen in training before a forecast is trusted.
RANGE_CHECK_FEATURES = BASE_FEATURES + ["minutes_injecting", "minutes_shut_in", "injected_volume_bbl"]

_cache_lock = threading.Lock()
# Held while models train, so a request arriving during start-up warm-up waits instead of retraining.
_analysis_compute_lock = threading.Lock()
_optimizer_compute_lock = threading.Lock()
_analysis_cache: dict[str, Any] = {}
_optimizer_cache: dict[str, Any] = {}


def _recording_mask(timestamps: pd.Series) -> pd.Series:
    mask = pd.Series(False, index=timestamps.index)
    for start, end in RECORDING_PERIODS:
        mask |= timestamps.between(pd.Timestamp(start), pd.Timestamp(end))
    return mask


def _recording_period(timestamps: pd.Series) -> pd.Series:
    period = pd.Series(-1, index=timestamps.index)
    for index, (start, end) in enumerate(RECORDING_PERIODS):
        period[timestamps.between(pd.Timestamp(start), pd.Timestamp(end))] = index
    return period


def _pump_speed_fit(known: pd.DataFrame) -> tuple[float, float]:
    """Straight-line fit of pump speed against flow rate from rows where both were logged."""
    known = known.dropna(subset=["flow_bpm", "pump_speed"])
    slope, intercept = np.polyfit(known["flow_bpm"], known["pump_speed"], 1)
    return float(slope), float(intercept)


def _fill_pump_speed(frame: pd.DataFrame) -> pd.DataFrame:
    """Estimate missing pump speed from flow rate instead of treating it as 0 (pump stopped).

    Pump speed was not logged during the first recording period although the well was
    injecting. A straight-line fit of pump speed against flow rate from the periods
    that logged both fills the gap; calc flow is pump speed times its fixed ratio.
    """
    missing = frame["pump_speed"].isna()
    frame["pump_speed_estimated"] = missing.astype(int)
    known = frame[~missing & frame["flow_bpm"].notna()]
    if missing.any() and len(known) >= 20:
        slope, intercept = _pump_speed_fit(known)
        flow = frame.loc[missing, "flow_bpm"].fillna(0)
        estimate = np.where(flow > 0, np.clip(slope * flow + intercept, 0, None), 0.0)
        frame.loc[missing, "pump_speed"] = estimate
        pumping = known["pump_speed"] > 0
        ratio = (known.loc[pumping, "calc_flow_from_pump_speed"] / known.loc[pumping, "pump_speed"]).median()
        calc_missing = missing & frame["calc_flow_from_pump_speed"].isna()
        frame.loc[calc_missing, "calc_flow_from_pump_speed"] = frame.loc[calc_missing, "pump_speed"] * ratio
    return frame


def _add_history_features(frame: pd.DataFrame) -> pd.DataFrame:
    """Add injection-history inputs, computed within each recording period from past rows only."""
    period = frame["period"]
    injecting = frame["flow_bpm"] > INJECTING_FLOW_BPM
    # Minutes since the previous reading; long logger gaps are capped so they do not count as injection time.
    step_minutes = frame.groupby("period")["timestamp"].diff().dt.total_seconds().div(60).fillna(0).clip(upper=5)
    stretch = ((injecting != injecting.shift()) | (period != period.shift())).cumsum()
    elapsed = step_minutes.groupby(stretch).cumsum()
    frame["injecting"] = injecting.astype(int)
    frame["minutes_injecting"] = elapsed.where(injecting, 0.0)
    frame["minutes_shut_in"] = elapsed.where(~injecting, 0.0)
    frame["injected_volume_bbl"] = (frame["flow_bpm"] * step_minutes).groupby(period).cumsum()
    for column in ["flow_bpm", "surface_temp", "temperature_before_triplex"]:
        rolling = (
            frame.set_index("timestamp").groupby("period")[column].rolling(ROLLING_WINDOW).mean()
        )
        frame[f"{column}_30min_mean"] = rolling.to_numpy()
    # Thermal memory: the well cools and warms over tens of minutes to hours, so exponentially
    # weighted averages with several half-lives capture how much cold CO2 went down recently.
    for column in THERMAL_MEMORY_COLUMNS:
        for halflife in THERMAL_HALFLIVES_MINUTES:
            frame[f"{column}_ewm{halflife}"] = (
                frame.set_index("timestamp").groupby("period")[column]
                .transform(lambda s, h=halflife: s.ewm(halflife=pd.Timedelta(minutes=h), times=s.index).mean())
                .to_numpy()
            )
    # Cold dose: cumulative flow times how much colder the CO2 is than the 120 °F reference.
    coldness = (COLD_DOSE_REFERENCE_F - frame["surface_temp"]).clip(lower=0)
    frame["cold_dose"] = (frame["flow_bpm"] * coldness * step_minutes).groupby(period).cumsum()
    return frame


def _prepare_frame(rows: list[dict[str, Any]]) -> pd.DataFrame:
    frame = pd.DataFrame(rows)
    if frame.empty:
        return frame
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], errors="coerce")
    frame = frame.dropna(subset=["timestamp"]).sort_values("timestamp")
    for column in RAW_FEATURES + ["bhp", "corrected_bhp", "bht"]:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    # Surface readings only exist inside the recording periods; everything else is dropped.
    frame["period"] = _recording_period(frame["timestamp"])
    frame = frame[frame["period"] >= 0].reset_index(drop=True)
    frame = _fill_pump_speed(frame)
    frame[RAW_FEATURES] = frame[RAW_FEATURES].fillna(0)
    for column in ["bhp", "corrected_bhp", "bht"]:
        frame[column] = frame[column].interpolate(method="linear").fillna(0)
    return _add_history_features(frame)


def _metrics(actual: np.ndarray, predicted: np.ndarray) -> dict[str, float]:
    return {
        "mae": float(mean_absolute_error(actual, predicted)),
        "mse": float(mean_squared_error(actual, predicted)),
        "rmse": float(np.sqrt(mean_squared_error(actual, predicted))),
        "r2": float(r2_score(actual, predicted)),
    }


def _candidates() -> dict[str, Any]:
    return {
        "Linear Regression": LinearRegression(),
        "Random Forest Regressor": RandomForestRegressor(random_state=42, n_jobs=-1),
        "Gradient Boosting Regressor": GradientBoostingRegressor(random_state=42),
    }


def _data_key(rows: list[dict[str, Any]]) -> tuple:
    return (len(rows), rows[-1]["timestamp"] if rows else None)


def _band(errors: np.ndarray) -> float | None:
    """Half-width of the error band: the INTERVAL_QUANTILE of absolute errors on unseen data."""
    errors = np.abs(np.asarray(errors, dtype=float))
    return float(np.quantile(errors, INTERVAL_QUANTILE)) if errors.size else None


def _period_holdout(frame: pd.DataFrame, target: str, model, features: list[str]):
    """Predict each recording period with a model trained on the other periods (injecting rows scored)."""
    periods, residuals = [], []
    for period in sorted(frame["period"].unique()):
        train, test = frame[frame["period"] != period], frame[frame["period"] == period]
        test = test[test["injecting"] == 1]
        if len(test) < 2 or train.empty:
            continue
        predicted = clone(model).fit(train[features], train[target]).predict(test[features])
        baseline = np.full(len(test), train.loc[train["injecting"] == 1, target].mean())
        start, end = RECORDING_PERIODS[period]
        periods.append(
            {
                "period": f"{start[:16]} to {end[:16]}",
                "rows": int(len(test)),
                "mae": float(mean_absolute_error(test[target], predicted)),
                "rmse": float(np.sqrt(mean_squared_error(test[target], predicted))),
                "baseline_mae": float(mean_absolute_error(test[target], baseline)),
            }
        )
        residuals.append(test[target].to_numpy() - predicted)
    return periods, (np.concatenate(residuals) if residuals else np.array([]))


def _select_model(frame: pd.DataFrame, target: str, features: list[str]) -> dict[str, Any]:
    """Score every candidate two ways and pick the one with the lowest average held-out-period error.

    1. Chronological: train on the earliest 80% of readings, test on the most recent 20%.
    2. Held-out periods: predict each recording period from the other two (injecting rows).
    Choosing on (2) judges each model on every operating period, not on one test window.
    """
    cut = int(len(frame) * (1 - TEST_FRACTION))
    x, y = frame[features], frame[target]
    x_train, x_test, y_train, y_test = x.iloc[:cut], x.iloc[cut:], y.iloc[:cut], y.iloc[cut:]
    scores, chrono_fitted, chrono_predicted, holdouts = {}, {}, {}, {}
    for name, model in _candidates().items():
        chrono_fitted[name] = model.fit(x_train, y_train)
        chrono_predicted[name] = model.predict(x_test)
        holdouts[name] = _period_holdout(frame, target, model, features)
        scores[name] = _metrics(y_test.to_numpy(), chrono_predicted[name])
        held_out_maes = [period["mae"] for period in holdouts[name][0]]
        scores[name]["holdout_mae"] = float(np.mean(held_out_maes)) if held_out_maes else float("nan")
    best = min(scores, key=lambda name: scores[name]["holdout_mae"])
    injecting_test = frame["injecting"].iloc[cut:].to_numpy() == 1
    recent_errors = (y_test.to_numpy() - chrono_predicted[best])[injecting_test if injecting_test.sum() >= 20 else slice(None)]
    return {
        "best": best,
        "scores": scores,
        "cut": cut,
        "chrono_model": chrono_fitted[best],
        "chrono_predicted": chrono_predicted[best],
        "injecting_test": injecting_test,
        "holdout_periods": holdouts[best][0],
        "band_recent": _band(recent_errors),
        "band_new_period": _band(holdouts[best][1]),
        "final_model": clone(_candidates()[best]).fit(x, y),
    }


def _value_at_offset(frame: pd.DataFrame, column: str, minutes: float, tolerance_seconds: float = 30) -> pd.Series:
    """The value of ``column`` ``minutes`` before (negative) or after (positive) each reading, within its period."""
    out = pd.Series(np.nan, index=frame.index)
    for _, group in frame.groupby("period"):
        series = group.set_index("timestamp")[column]
        series = series[~series.index.duplicated()]
        wanted = group["timestamp"] + pd.Timedelta(minutes=minutes)
        out.loc[group.index] = series.reindex(
            wanted, method="nearest", tolerance=pd.Timedelta(seconds=tolerance_seconds)
        ).to_numpy()
    return out


def _live_feature_names(target: str) -> list[str]:
    return [f"{target}_now"] + [f"{target}_change_{minutes}" for minutes in LIVE_TREND_MINUTES]


def _add_live_features(frame: pd.DataFrame, target: str) -> pd.DataFrame:
    """Latest measured value and its recent trend, used by the live-anchored projection."""
    frame = frame.copy()
    frame[f"{target}_now"] = frame[target]
    for minutes in LIVE_TREND_MINUTES:
        frame[f"{target}_change_{minutes}"] = frame[target] - _value_at_offset(frame, target, -minutes)
    return frame


def _live_model():
    return RandomForestRegressor(n_estimators=100, min_samples_leaf=5, max_features=0.5, random_state=42, n_jobs=-1)


def _train_live_models(frame: pd.DataFrame, target: str) -> dict[str, Any]:
    """Train the live-gauge change models (one per horizon) and measure them on held-out periods.

    For each horizon a model predicts the change from the current reading, using the surface
    inputs plus the reading's recent trend. Each model is tested by predicting every recording
    period from the other two and compared with assuming the value stays the same; if it does
    not beat that, the projection uses "stays the same" for that horizon. The error band is the
    90% quantile of held-out errors of whichever method is used.
    """
    data = _add_live_features(frame, target)
    features = TARGET_FEATURES[target] + _live_feature_names(target)
    horizons = []
    for minutes in FORECAST_HORIZONS_MINUTES:
        data["future_change"] = _value_at_offset(data, target, minutes) - data[target]
        usable = data.dropna(subset=features + ["future_change"])
        model_errors, persistence_errors = [], []
        for period in sorted(usable["period"].unique()):
            train, test = usable[usable["period"] != period], usable[usable["period"] == period]
            if len(test) < 20 or train.empty:
                continue
            predicted_change = _live_model().fit(train[features], train["future_change"]).predict(test[features])
            model_errors.append(test["future_change"].to_numpy() - predicted_change)
            persistence_errors.append(test["future_change"].to_numpy())
        model_errors = np.concatenate(model_errors) if model_errors else np.array([])
        persistence_errors = np.concatenate(persistence_errors) if persistence_errors else np.array([])
        model_mae = float(np.mean(np.abs(model_errors))) if model_errors.size else float("nan")
        persistence_mae = float(np.mean(np.abs(persistence_errors))) if persistence_errors.size else float("nan")
        use_model = bool(model_errors.size) and model_mae < persistence_mae
        horizons.append(
            {
                "minutes": minutes,
                "model": _live_model().fit(usable[features], usable["future_change"]) if use_model else None,
                "band": (_band(model_errors) if use_model else _band(persistence_errors)) or 0.0,
                "model_mae": model_mae,
                "persistence_mae": persistence_mae,
                "improvement_pct": float((1 - model_mae / persistence_mae) * 100) if persistence_mae else None,
            }
        )
    data = data.drop(columns=["future_change"])
    return {"data": data, "features": features, "horizons": horizons}


def _live_projection(trained: dict[str, Any], target: str, anchor: int) -> dict[str, Any]:
    """Project the target 10, 30 and 60 minutes ahead from the reading at row ``anchor``."""
    data, features = trained["data"], trained["features"]
    row = data.iloc[[anchor]].copy()
    anchor_time = data["timestamp"].iloc[anchor]
    latest_value = float(data[target].iloc[anchor])
    # The trend inputs need a reading within 30 s of 5 and 15 minutes earlier (as in training). The logger
    # has gaps of over a minute, so when one is missing for this reading, accept the nearest reading
    # within 2 minutes of that time instead of dropping the model for this projection.
    period_values = data[data["period"] == data["period"].iloc[anchor]].set_index("timestamp")[target]
    period_values = period_values[~period_values.index.duplicated()]
    for minutes in LIVE_TREND_MINUTES:
        column = f"{target}_change_{minutes}"
        if pd.isna(row[column].iloc[0]):
            earlier = period_values.reindex(
                [anchor_time - pd.Timedelta(minutes=minutes)], method="nearest", tolerance=pd.Timedelta(minutes=2)
            ).iloc[0]
            if pd.notna(earlier):
                row[column] = latest_value - float(earlier)
    ready = bool(row[features].notna().all(axis=1).iloc[0])
    horizons = []
    for horizon in trained["horizons"]:
        use_model = horizon["model"] is not None and ready
        change = float(horizon["model"].predict(row[features])[0]) if use_model else 0.0
        horizons.append(
            {
                "minutes": horizon["minutes"],
                "method": "model" if use_model else "stays the same",
                "predicted": latest_value + change,
                "band": horizon["band"],
                "model_mae": horizon["model_mae"],
                "persistence_mae": horizon["persistence_mae"],
                "improvement_pct": horizon["improvement_pct"],
            }
        )
    return {
        "anchor_time": data["timestamp"].iloc[anchor].isoformat(),
        "anchor_value": float(data[target].iloc[anchor]),
        "horizons": horizons,
        "trend_unavailable": not ready,
    }


def _future_features(frame: pd.DataFrame, features: list[str]) -> pd.DataFrame:
    """Inputs for the held-constant projection: latest operating conditions held constant.

    Time-based inputs keep counting (minutes injecting or shut in, injected volume, cold dose),
    and the 30-minute and thermal-memory averages move toward the held-constant values.
    """
    latest = frame.iloc[-1]
    rows = []
    for step in range(1, FORECAST_HORIZON_MINUTES // FORECAST_STEP_MINUTES + 1):
        minutes = step * FORECAST_STEP_MINUTES
        row = latest.copy()
        if latest["injecting"]:
            row["minutes_injecting"] = latest["minutes_injecting"] + minutes
            row["injected_volume_bbl"] = latest["injected_volume_bbl"] + latest["flow_bpm"] * minutes
            coldness = max(COLD_DOSE_REFERENCE_F - latest["surface_temp"], 0.0)
            row["cold_dose"] = latest["cold_dose"] + latest["flow_bpm"] * coldness * minutes
        else:
            row["minutes_shut_in"] = latest["minutes_shut_in"] + minutes
        weight = min(minutes / 30, 1.0)
        for column in THERMAL_MEMORY_COLUMNS:
            row[f"{column}_30min_mean"] = (1 - weight) * latest[f"{column}_30min_mean"] + weight * latest[column]
            for halflife in THERMAL_HALFLIVES_MINUTES:
                decay = 0.5 ** (minutes / halflife)
                row[f"{column}_ewm{halflife}"] = latest[column] + (latest[f"{column}_ewm{halflife}"] - latest[column]) * decay
        rows.append(row)
    return pd.DataFrame(rows)[features]


def _held_constant_forecast(frame: pd.DataFrame, target: str, features: list[str], model, band: float,
                            training: pd.DataFrame | None = None) -> dict[str, Any]:
    """Surface-data model run forward for the next hour from the last row of ``frame``, conditions held constant.

    ``training`` is the data the model learned from, used to flag inputs outside its range (defaults to ``frame``).
    """
    training = frame if training is None else training
    future_x = _future_features(frame, features)
    values = model.predict(future_x)
    anchor_time = frame["timestamp"].iloc[-1]
    points = [
        {
            "timestamp": (anchor_time + pd.Timedelta(minutes=(index + 1) * FORECAST_STEP_MINUTES)).strftime("%Y-%m-%dT%H:%M:%S"),
            "predicted": float(value),
            "lower": float(value - band),
            "upper": float(value + band),
            "extrapolated": bool(_out_of_range(training, future_x.iloc[index])),
        }
        for index, value in enumerate(values)
    ]
    horizons = [
        {
            "minutes": minutes,
            "method": "held constant",
            "predicted": points[minutes // FORECAST_STEP_MINUTES - 1]["predicted"],
            "band": band,
            "model_mae": None,
            "persistence_mae": None,
            "improvement_pct": None,
        }
        for minutes in FORECAST_HORIZONS_MINUTES
    ]
    return {
        "anchor_time": anchor_time.isoformat(),
        "anchor_value": float(frame[target].iloc[-1]),
        "horizons": horizons,
        "points": points,
        "out_of_range_end": _out_of_range(training, future_x.iloc[-1]),
    }


def _forecast_points(live: dict[str, Any]) -> list[dict[str, Any]]:
    """1-minute points through the forecast horizons, interpolating values and bands between them."""
    anchor_time = pd.Timestamp(live["anchor_time"])
    knots_minutes = [0] + [h["minutes"] for h in live["horizons"]]
    knots_value = [live["anchor_value"]] + [h["predicted"] for h in live["horizons"]]
    knots_band = [0.0] + [h["band"] for h in live["horizons"]]
    points = []
    for minute in range(FORECAST_STEP_MINUTES, FORECAST_HORIZON_MINUTES + 1, FORECAST_STEP_MINUTES):
        value = float(np.interp(minute, knots_minutes, knots_value))
        band = float(np.interp(minute, knots_minutes, knots_band))
        points.append(
            {
                "timestamp": (anchor_time + pd.Timedelta(minutes=minute)).strftime("%Y-%m-%dT%H:%M:%S"),
                "predicted": value,
                "lower": value - band,
                "upper": value + band,
                "extrapolated": False,
            }
        )
    return points


PROJECTION_ASSUMPTIONS = {
    "live": (
        "Projection starts from the latest measured value and predicts how it will change over the next "
        "10, 30 and 60 minutes if operating conditions stay as they are now. Error bands come from "
        "predicting recording periods the model had not seen."
    ),
    "held_constant": (
        "Projection from the surface-data model with the latest operating conditions (flow, surface pressure "
        "and temperatures) held constant for the next hour. It is not a forecast of operator actions. The band "
        "is the 90% error on unseen recent data."
    ),
}


def _projection(frame: pd.DataFrame, target: str, artifact: dict[str, Any], anchor: int):
    """Next-hour projection starting from row ``anchor`` of ``frame``; returns ``(forecast, points)``."""
    method = artifact["method"]
    if method == "live":
        projection = _live_projection(artifact["live"], target, anchor)
        points = _forecast_points(projection)
        out_of_range_end = []
    else:
        projection = _held_constant_forecast(
            frame.iloc[: anchor + 1], target, artifact["features"], artifact["model"], artifact["band"], training=frame
        )
        points = projection["points"]
        out_of_range_end = projection["out_of_range_end"]
    forecast = {
        "horizon_minutes": FORECAST_HORIZON_MINUTES,
        "step_minutes": FORECAST_STEP_MINUTES,
        "starts_after": projection["anchor_time"],
        "method": method,
        "anchor_value": projection["anchor_value"],
        "horizons": projection["horizons"],
        "assumption": PROJECTION_ASSUMPTIONS[method],
        "trend_unavailable": bool(projection.get("trend_unavailable", False)),
        "out_of_range_now": _out_of_range(frame, frame.iloc[anchor]),
        "out_of_range_end": out_of_range_end,
    }
    return forecast, points


def _out_of_range(training: pd.DataFrame, row: pd.Series) -> list[str]:
    """Inputs outside the range seen in training (the model would be extrapolating)."""
    # The ranges are computed once per training frame and kept on it.
    ranges = training.attrs.get("feature_ranges")
    if ranges is None:
        ranges = {column: (training[column].min(), training[column].max()) for column in RANGE_CHECK_FEATURES}
        training.attrs["feature_ranges"] = ranges
    flagged = []
    for column in RANGE_CHECK_FEATURES:
        low, high = ranges[column]
        if not low <= row[column] <= high:
            flagged.append(f"{column} = {row[column]:,.2f} (training range {low:,.2f} to {high:,.2f})")
    return flagged


def _fit_target(frame: pd.DataFrame, target: str, label: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """Train and evaluate one target; returns ``(result for the API, artifacts for later projections)``."""
    if len(frame) < 20:
        raise ValueError("At least 20 active fulldata rows are required for prediction")
    unit = UNITS[target]
    features = TARGET_FEATURES[target]
    selection = _select_model(frame, target, features)
    best_name, cut = selection["best"], selection["cut"]
    x, y = frame[features], frame[target]
    y_test, best_predicted = y.iloc[cut:].to_numpy(), selection["chrono_predicted"]
    injecting_test = selection["injecting_test"]
    test_frame = pd.DataFrame(
        {
            "timestamp": frame["timestamp"].iloc[cut:].dt.strftime("%Y-%m-%dT%H:%M:%S"),
            "actual": y_test,
            "predicted": best_predicted,
            "residual": y_test - best_predicted,
            "injecting": injecting_test,
        }
    )
    random_x_train, random_x_test, random_y_train, random_y_test = train_test_split(
        x, y, test_size=TEST_FRACTION, random_state=42
    )
    random_model = clone(_candidates()[best_name]).fit(random_x_train, random_y_train)

    best_model = selection["chrono_model"]
    importance = best_model.feature_importances_ if hasattr(best_model, "feature_importances_") else np.abs(best_model.coef_)
    feature_importance = [
        {"feature": feature, "importance": float(value)}
        for feature, value in sorted(zip(features, importance), key=lambda item: item[1], reverse=True)
    ]

    method = PROJECTION_METHOD[target]
    # Everything needed to project from any reading later (the dashboard's simulated time).
    artifact = {
        "method": method,
        "features": features,
        "model": selection["final_model"],
        "band": selection["band_recent"] or 0.0,
        "live": _train_live_models(frame, target) if method == "live" else None,
    }
    forecast, future_predictions = _projection(frame, target, artifact, len(frame) - 1)

    evaluation = {
        "method": "chronological",
        "description": (
            f"Trained on the earliest {1 - TEST_FRACTION:.0%} of readings and tested on the most recent "
            f"{TEST_FRACTION:.0%}, which the model has not seen."
        ),
        "selection": (
            "Model chosen by the lowest average error when predicting each recording period from the "
            "other two (injecting readings)."
        ),
        "train_rows": int(cut),
        "test_rows": int(len(y_test)),
        "test_start": frame["timestamp"].iloc[cut].isoformat(),
        "test_end": frame["timestamp"].iloc[-1].isoformat(),
        "injecting_test_rows": int(injecting_test.sum()),
        "best_model_injecting_metrics": (
            _metrics(y_test[injecting_test], best_predicted[injecting_test]) if injecting_test.sum() >= 2 else None
        ),
        "random_split_metrics": _metrics(random_y_test.to_numpy(), random_model.predict(random_x_test)),
        "period_holdout": selection["holdout_periods"],
        "interval": {
            "quantile": INTERVAL_QUANTILE,
            "unit": unit,
            "recent_conditions": selection["band_recent"],
            "new_period": selection["band_new_period"],
        },
        "forecast": forecast,
        "features": features,
    }
    result = {
        "label": label,
        "best_model": best_name,
        "metrics": selection["scores"],
        "test_predictions": test_frame.to_dict(orient="records"),
        "future_predictions": future_predictions,
        "feature_importance": feature_importance,
        "row_count": int(len(frame)),
        "evaluation": evaluation,
    }
    return result, artifact


def _db_data_key(db) -> tuple:
    """Cheap version check (row count + latest timestamp), the same key _data_key builds from loaded rows."""
    count, latest = db.query(func.count(models.FullData.timestamp), func.max(models.FullData.timestamp)).one()
    return (int(count or 0), latest)


def analyze_fulldata(db) -> dict[str, Any]:
    key = _db_data_key(db)
    with _analysis_compute_lock:
        with _cache_lock:
            if _analysis_cache.get("key") == key:
                return _analysis_cache["result"]
        rows = full_data_rows(db)
        key = _data_key(rows)
        frame = _prepare_frame(rows)
        if frame.empty:
            raise ValueError("No fulldata rows are available")
        result = {
            "source": "fulldata",
            "recording_periods": [{"start": start, "end": end} for start, end in RECORDING_PERIODS],
            "row_count": int(len(frame)),
        }
        artifacts = {}
        for key_name, (target, label) in TARGETS.items():
            result[key_name], artifacts[key_name] = _fit_target(frame, target, label)
        with _cache_lock:
            _analysis_cache.update({"key": key, "result": result, "frame": frame, "artifacts": artifacts})
        return result


def outlook_at(db, at: pd.Timestamp | None) -> dict[str, Any]:
    """Next-hour projection for CBHP and BHT starting from the latest reading at or before ``at``.

    Used by the dashboard to start the outlook from its simulated clock. The models are the ones trained
    in analyze_fulldata (on all recorded data), so nothing is retrained here.
    """
    analyze_fulldata(db)
    with _cache_lock:
        frame, artifacts = _analysis_cache["frame"], _analysis_cache["artifacts"]
    at = frame["timestamp"].iloc[-1] if at is None else pd.Timestamp(at)
    anchor = int(frame["timestamp"].searchsorted(at, side="right")) - 1
    if anchor < 0:
        raise ValueError(f"No recorded surface readings at or before {at:%Y-%m-%d %H:%M:%S}")
    anchor_time = frame["timestamp"].iloc[anchor]
    result = {
        "requested_at": at.isoformat(),
        "anchor_time": anchor_time.isoformat(),
        "minutes_since_reading": float((at - anchor_time).total_seconds() / 60),
    }
    for key_name, (target, _) in TARGETS.items():
        forecast, points = _projection(frame, target, artifacts[key_name], anchor)
        result[key_name] = {"forecast": forecast, "future_predictions": points}
    return result


def warm_up(db) -> None:
    """Train the prediction and optimizer models ahead of the first page request."""
    analyze_fulldata(db)
    _optimization_models(db)


def _optimization_models(db) -> dict[str, Any]:
    """Train (once per data version) the CBHP and BHT models used by the optimizer."""
    with _optimizer_compute_lock:
        with _cache_lock:
            if _optimizer_cache.get("key") == _db_data_key(db):
                return _optimizer_cache["models"]
        return _train_optimization_models(full_data_rows(db))


def _constrained_model(features: list[str], signs: dict[str, int]) -> HistGradientBoostingRegressor:
    """Gradient boosting whose prediction can only rise (+1) or fall (-1) with the named inputs."""
    return HistGradientBoostingRegressor(
        monotonic_cst=[signs.get(feature, 0) for feature in features], max_iter=300, learning_rate=0.05, random_state=42
    )


def _train_optimization_models(rows: list[dict[str, Any]]) -> dict[str, Any]:
    key = _data_key(rows)
    with _cache_lock:
        if _optimizer_cache.get("key") == key:
            return _optimizer_cache["models"]
    frame = _prepare_frame(rows)
    if len(frame) < 20:
        raise ValueError("At least 20 active fulldata rows are required for optimization")
    models = {}

    # CBHP: two-stage, physics-constrained. Tested on real flow changes 15 minutes apart, it predicted the
    # direction of the CBHP change correctly 90% of the time (52% for the earlier single-stage model) and its
    # error on unseen recording periods fell from 41.2 to 37.1 psi.
    cbhp_features = OPTIMIZATION_FEATURES["cbhp"]
    cut = int(len(frame) * (1 - TEST_FRACTION))
    recent_model = _constrained_model(cbhp_features, OPTIMIZER_CBHP_MONOTONIC).fit(
        frame.iloc[:cut][cbhp_features], frame.iloc[:cut]["corrected_bhp"]
    )
    recent = frame.iloc[cut:]
    recent = recent[recent["injecting"] == 1] if (recent["injecting"] == 1).sum() >= 20 else recent
    models["cbhp"] = {
        "model": _constrained_model(cbhp_features, OPTIMIZER_CBHP_MONOTONIC).fit(frame[cbhp_features], frame["corrected_bhp"]),
        "name": OPTIMIZER_CBHP_MODEL_NAME,
        "margin": _band(recent["corrected_bhp"].to_numpy() - recent_model.predict(recent[cbhp_features])) or 0.0,
    }
    models["stage1"] = {
        column: _constrained_model(OPTIMIZER_STAGE1_INPUTS, {"flow_bpm": sign}).fit(frame[OPTIMIZER_STAGE1_INPUTS], frame[column])
        for column, sign in OPTIMIZER_LINKED_RESPONSE.items()
    }

    # BHT: kept as an indicative single-stage model. Neither approach beat "assume no change" when predicting
    # BHT after a real flow change, because BHT responds to flow slowly (thermal lag).
    selection = _select_model(frame, "bht", OPTIMIZATION_FEATURES["bht"])
    models["bht"] = {
        "model": selection["final_model"],
        "name": selection["best"],
        "margin": selection["band_recent"] or 0.0,
        "holdout_mae": selection["scores"][selection["best"]]["holdout_mae"],
    }
    injecting = frame[frame["injecting"] == 1]
    models["flow_cap_bpm"] = float(injecting["flow_bpm"].max())
    models["pump_fit"] = _pump_speed_fit(frame[frame["pump_speed_estimated"] == 0])
    with _cache_lock:
        _optimizer_cache.update({"key": key, "models": models})
    return models


def optimize_injection(db, request: dict[str, Any]) -> dict[str, Any]:
    """Search flow rates and recommend one whose predicted value plus its error margin meets the limit."""
    models = _optimization_models(db)
    mode = request.get("mode")
    inputs = request.get("inputs", {})
    cbhp, bht = models["cbhp"], models["bht"]
    flow_cap = models["flow_cap_bpm"]
    slope, intercept = models["pump_fit"]

    flow_min = max(0.0, float(request.get("flow_min", 0)))
    requested_max = max(flow_min, float(request.get("flow_max", 100)))
    if flow_min > flow_cap:
        raise ValueError(
            f"The search starts at {flow_min:.2f} BPM, above the highest flow in the data ({flow_cap:.2f} BPM). "
            "The models cannot predict reliably there."
        )
    flow_max = min(requested_max, flow_cap)
    flow_step = max(0.01, float(request.get("flow_step", 1)))
    flows = np.arange(flow_min, flow_max + flow_step / 2, flow_step)
    flows = flows[flows <= flow_max + 1e-9]

    # Stage 1: the flow-linked surface readings move with the tested flow. Each moves by its model's expected
    # response from the current flow to the tested flow, anchored to the reading the user entered. Without a
    # current flow the readings are held as entered.
    current_flow = inputs.get("flow_bpm")
    annulus = float(inputs.get("annulus_psi", 0))
    stage1 = models["stage1"]
    anchor_response = (
        {column: float(model.predict(pd.DataFrame([{"flow_bpm": float(current_flow), "annulus_psi": annulus}]))[0])
         for column, model in stage1.items()}
        if current_flow is not None
        else None
    )

    def predict(flow):
        pump_speed = float(np.clip(slope * flow + intercept, 0, None)) if flow > 0 else 0.0
        cbhp_row = {feature: float(inputs.get(feature, 0)) for feature in OPTIMIZATION_FEATURES["cbhp"]}
        bht_row = {feature: float(inputs.get(feature, 0)) for feature in OPTIMIZATION_FEATURES["bht"]}
        for row in (cbhp_row, bht_row):
            row["flow_bpm"] = float(flow)
            row["pump_speed"] = pump_speed
        if anchor_response is not None:
            tested = pd.DataFrame([{"flow_bpm": float(flow), "annulus_psi": annulus}])
            for column, model in stage1.items():
                if column in cbhp_row:
                    cbhp_row[column] = float(inputs.get(column, 0)) + float(model.predict(tested)[0]) - anchor_response[column]
        predicted_cbhp = float(cbhp["model"].predict(pd.DataFrame([cbhp_row]))[0])
        predicted_bht = float(bht["model"].predict(pd.DataFrame([bht_row]))[0])
        return {
            "flow_bpm": float(flow),
            "pump_speed": pump_speed,
            "predicted_cbhp": predicted_cbhp,
            "predicted_cbhp_upper": predicted_cbhp + cbhp["margin"],
            "predicted_bht": predicted_bht,
            "predicted_bht_upper": predicted_bht + bht["margin"],
        }

    results = [predict(flow) for flow in flows]
    common = {
        "mode": mode,
        "models": {"cbhp": cbhp["name"], "bht": bht["name"]},
        "cbhp_margin": cbhp["margin"],
        "bht_margin": bht["margin"],
        "interval_quantile": INTERVAL_QUANTILE,
        "flow_cap_bpm": flow_cap,
        "flow_search_capped": requested_max > flow_cap,
        "current_flow_bpm": float(current_flow) if current_flow is not None else None,
        "results": results,
        "decision_rule": (
            f"A flow rate is accepted only if the predicted value plus its {INTERVAL_QUANTILE:.0%} error margin "
            "stays within the limit. Pump speed is set from the flow rate."
        ),
        "cbhp_method": (
            "Two-stage, physics-constrained: surface pressure, surface temperature and pump-inlet conditions move with "
            "the tested flow (anchored to the current reading), and predicted CBHP can only rise as flow or surface "
            "pressure rises."
            if anchor_response is not None
            else "Surface conditions are held as entered; enter the current flow rate to let them move with the tested flow."
        ),
        "bht_reliability": (
            "Indicative only: in tests on real flow changes, BHT predictions were less accurate than assuming BHT stays "
            "the same, because BHT responds to flow slowly."
        ),
    }
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
        acceptable = [row for row in results if row["predicted_cbhp_upper"] <= limit]
        if not acceptable:
            raise ValueError(
                f"No flow rate in the searched range keeps predicted CBHP plus its error margin "
                f"(±{cbhp['margin']:.1f} psi) within {limit:,.1f} psi"
            )
        selected = acceptable[-1]
        result = {
            **common,
            "recommended_flow_bpm": selected["flow_bpm"],
            "predicted_cbhp": selected["predicted_cbhp"],
            "predicted_cbhp_upper": selected["predicted_cbhp_upper"],
            "predicted_bht": selected["predicted_bht"],
            "cbhp_limit": limit,
        }
        if mode == "safe_operation":
            result.update(
                {
                    "maximum_allowable_cbhp": maximum_allowable_cbhp,
                    "safety_margin_pct": safety_margin_pct,
                    "safe_operating_limit": limit,
                    "remaining_pressure_margin": limit - selected["predicted_cbhp_upper"],
                }
            )
        return result

    if mode == "temperature_control":
        limit = float(request["bht_limit"])
        acceptable = [row for row in results if row["predicted_bht_upper"] <= limit]
        if not acceptable:
            closest = min(results, key=lambda row: row["predicted_bht_upper"])
            return {**common, "feasible": False, "bht_limit": limit, "closest_result": closest, "acceptable_results": []}
        return {
            **common,
            "feasible": True,
            "bht_limit": limit,
            "acceptable_flow_min_bpm": acceptable[0]["flow_bpm"],
            "acceptable_flow_max_bpm": acceptable[-1]["flow_bpm"],
            "acceptable_results": acceptable,
        }
    raise ValueError("Unsupported optimization mode")
