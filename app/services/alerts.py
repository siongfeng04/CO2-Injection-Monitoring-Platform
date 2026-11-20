"""Alerts for the digital twin: sensor faults, operating limits, rates of change and model mismatch.

Each check flags individual readings using only that reading and earlier ones, so the dashboard can show
exactly what an operator would have seen at its simulated time. ``alerts_until`` then groups the flagged
readings up to that time into events. Limits and actions come from
docs/knowledge_base/co2_injection_thresholds.md (project design-basis values, not regulatory limits).
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

WARNING, CRITICAL = 1, 2
SEVERITY_NAMES = {WARNING: "warning", CRITICAL: "critical"}
CATEGORIES = {
    "sensor": "Sensor fault",
    "limit": "Operating limit",
    "rate": "Rate of change",
    "model": "Model mismatch",
    "drift": "Gradual drift",
}

# Operating limits (knowledge base sections 2-8). Low limits on the injection readings only apply while
# injecting: pressure and temperature fall naturally during shut-in.
LIMIT_RULES = [
    # column, label, unit, (warning high, critical high), (warning low, critical low), low only while injecting
    ("corrected_bhp", "Corrected bottom-hole pressure", "psi", (1980.0, 2200.0), (1071.0, None), True),
    ("bht", "Bottom-hole temperature", "°F", (120.0, 125.0), (87.98, None), True),
    ("surface_psi", "Surface pressure", "psi", (1550.0, 1600.0), (None, None), False),
    ("surface_temp", "Surface temperature", "°F", (120.0, 130.0), (90.0, 80.0), True),
    ("annulus_psi", "Annulus pressure", "psi", (2000.0, 2500.0), (None, None), False),
    ("flow_bpm", "Flow rate", "bpm", (4.9, 5.0), (None, None), False),
    ("pump_speed", "Pump speed", "", (390.0, 420.0), (None, None), False),
    ("pressure_before_triplex", "Pump-inlet pressure", "psi", (None, None), (220.0, 200.0), True),
    ("temperature_before_triplex", "Pump-inlet temperature", "°F", (10.0, 20.0), (None, None), False),
]
# Pump-inlet (cavitation) limits only matter while the pump is moving CO2: before start-up the suction
# line sits at ambient temperature (up to ~69 °F in this dataset).
INJECTING_ONLY_COLUMNS = {"pressure_before_triplex", "temperature_before_triplex"}
LIMIT_ACTIONS = {
    ("corrected_bhp", "high", WARNING): "Reduce the injection rate and watch the pressure trend.",
    ("corrected_bhp", "high", CRITICAL): "Stop injection (shut-in) and inform the responsible engineer.",
    ("corrected_bhp", "low", WARNING): (
        "CO2 may not be supercritical at the bottom of the well. Check the gauge, flow rate and CO2 supply."
    ),
    ("bht", "low", WARNING): "Strong cooling by cold CO2. Watch for thermal stress and check the injection rate.",
    ("surface_psi", "high", WARNING): "Do not raise the pump speed further.",
    ("surface_psi", "high", CRITICAL): "Reduce the rate or stop the pump.",
    ("surface_temp", "high", WARNING): "Check the pump and the CO2 supply temperature.",
    ("surface_temp", "low", WARNING): "Check the pump and the CO2 supply temperature.",
    ("annulus_psi", "high", CRITICAL): (
        "Treat as a possible well-integrity problem: reduce or stop injection and do not restart until "
        "integrity is confirmed."
    ),
    ("pressure_before_triplex", "low", WARNING): "Suction pressure is close to cavitation. Check the CO2 supply.",
    ("pressure_before_triplex", "low", CRITICAL): "Risk of cavitation in the pump. Reduce the rate and check the CO2 supply.",
    ("temperature_before_triplex", "high", WARNING): "Warm CO2 at the pump inlet raises the cavitation risk. Check the supply.",
}
DEFAULT_ACTIONS = {
    WARNING: "Confirm the reading is real, stop increasing the rate and watch the trend.",
    CRITICAL: "Reduce the injection rate immediately; if the value does not recover, stop injection and inform the engineer.",
}

# Rates of change (knowledge base sections 4 and 6). The BHT drop is checked only after an hour of
# injection: the well always cools sharply when the pumps start, which is expected.
BHT_DROP_F, BHT_DROP_MINUTES, BHT_DROP_AFTER_INJECTING_MINUTES = 5.0, 60, 60
ANNULUS_CHANGE_PSI, ANNULUS_CHANGE_MINUTES, ANNULUS_FLOW_STEADY_BPM = 200.0, 10, 0.5

# Sensor faults.
ANNULUS_MAX_PSI = 3000.0  # the same limit prediction.py uses to clean the 10,313 psi glitch
CBHP_MIN_REAL_PSI = 100.0  # below this the gauge was pulled or the logger stopped (knowledge base section 3)
LOGGER_GAP_MINUTES = 5.0
STUCK_MINUTES = 10.0
STUCK_COLUMNS = {"corrected_bhp": "CBHP", "bht": "BHT", "surface_psi": "Surface pressure", "annulus_psi": "Annulus pressure"}

# Model mismatch: the measured value departs from what the surface readings predict by more than the
# model's 90% error band on unseen periods, for a sustained time. Checked after the first hour of
# injection, where the models are reliable (CBHP cannot be predicted during start-up).
MODEL_SMOOTHING = "3min"
MODEL_AFTER_INJECTING_MINUTES = 60
MODEL_CRITICAL_BANDS = 2.0

# Gradual drift: a two-sided CUSUM (cumulative sum) on the same model gap. The model check only fires once
# the gap passes the error band; CUSUM adds up small persistent changes, so a slow drift is found before it
# gets that large. In each steady-injection stretch the gap's baseline is its median over the first
# DRIFT_BASELINE_MINUTES (this absorbs a constant model bias for that period). After that, every minute the
# gap differs from the baseline by more than the allowance k (DRIFT_K_BANDS x band) adds the excess to the
# sum; an alert is raised when the sum passes h (DRIFT_H_BAND_MINUTES x band, in unit-minutes). For a steady
# offset d > k this takes h / (d - k) minutes, e.g. CBHP (k = 36 psi, h = 240 psi-min): a 48 psi offset after
# ~20 min. k and h were chosen with scripts/evaluate_alerts.py --grid: with k = 0.25x band the drift alert was
# on for 24 of the 37 gauge-hours of clean steady injection (the model gap wanders by up to one band over
# hours); k = 0.75x, h = 5x keeps it to 0.5 h while catching 50% of 0.25x-band-per-hour CBHP drifts (13% without
# the drift check) and 97% of 1x-band-per-hour BHT drifts.
DRIFT_SMOOTHING = "1min"
DRIFT_BASELINE_MINUTES = 30.0
DRIFT_K_BANDS = 0.75
DRIFT_H_BAND_MINUTES = 5.0

# Grouping: flagged readings less than MERGE_MINUTES apart (by category) form one event, so a reading
# hovering around a limit raises one alert, not one per crossing; an event must last MIN_MINUTES before
# it is raised, so single noisy readings do not alarm.
MERGE_MINUTES = {"sensor": 2.0, "limit": 10.0, "rate": 10.0, "model": 5.0, "drift": 10.0}
MIN_MINUTES = {"sensor": 0.0, "limit": 1.0, "rate": 1.0, "model": 2.0, "drift": 1.0}
# An event is "active" if its last flagged reading is this close to the latest reading.
ACTIVE_WITHIN_MINUTES = 2.0


def _minutes_ago(frame: pd.DataFrame, column: str, minutes: float) -> pd.Series:
    """Value of ``column`` about ``minutes`` before each reading, within its recording period."""
    out = pd.Series(np.nan, index=frame.index)
    for _, group in frame.groupby("period"):
        series = group.set_index("timestamp")[column]
        series = series[~series.index.duplicated()]
        wanted = group["timestamp"] - pd.Timedelta(minutes=minutes)
        out.loc[group.index] = series.reindex(wanted, method="nearest", tolerance=pd.Timedelta(seconds=60)).to_numpy()
    return out


def _minutes_unchanged(frame: pd.DataFrame, column: str) -> pd.Series:
    """Minutes since ``column`` last changed value (past readings only)."""
    run = ((frame[column] != frame[column].shift()) | (frame["period"] != frame["period"].shift())).cumsum()
    start = frame.groupby(run)["timestamp"].transform("min")
    return (frame["timestamp"] - start).dt.total_seconds() / 60


def _trailing_median(frame: pd.DataFrame, values: pd.Series, window: str) -> pd.Series:
    """Trailing rolling median of ``values`` within each recording period (past readings only)."""
    smoothed = (
        pd.Series(values.to_numpy(dtype=float), index=pd.DatetimeIndex(frame["timestamp"]))
        .groupby(frame["period"].to_numpy())
        .transform(lambda s: s.rolling(window, min_periods=1).median())
        .to_numpy()
    )
    return pd.Series(smoothed, index=frame.index)


def _cusum_drift(frame: pd.DataFrame, gap: pd.Series, steady: pd.Series, valid: pd.Series, band: float):
    """Two-sided CUSUM of ``gap`` against its baseline in each steady-injection stretch (see DRIFT_* above).

    Returns ``(alarm, drift, baseline_time)``: alarm is True where either sum passes h, drift is the gap
    minus its baseline, and baseline_time is when that stretch's baseline was set.
    """
    k, h = DRIFT_K_BANDS * band, DRIFT_H_BAND_MINUTES * band
    minutes = ((frame["timestamp"] - frame["timestamp"].iloc[0]).dt.total_seconds() / 60).to_numpy()
    stretch = ((steady != steady.shift()) | (frame["period"] != frame["period"].shift())).cumsum().to_numpy()
    in_stretch, ok, values = steady.to_numpy(), valid.to_numpy(), gap.to_numpy(dtype=float)
    n = len(values)
    alarm, drift, baseline_time = np.zeros(n, dtype=bool), np.full(n, np.nan), np.full(n, np.nan)
    current, start, last, baseline, buffer, up, down = None, 0.0, 0.0, np.nan, [], 0.0, 0.0
    set_at = np.nan
    for i in range(n):
        if not in_stretch[i]:
            current = None
            continue
        if stretch[i] != current:  # a new steady stretch: start a new baseline and reset the sums
            current, start, last, baseline, buffer, up, down = stretch[i], minutes[i], minutes[i], np.nan, [], 0.0, 0.0
        step = min(minutes[i] - last, 1.0)  # logger gaps do not count as time spent drifting
        last = minutes[i]
        if not ok[i] or np.isnan(values[i]):
            continue
        if minutes[i] - start < DRIFT_BASELINE_MINUTES:
            buffer.append(values[i])
            continue
        if np.isnan(baseline):
            baseline = float(np.median(buffer)) if buffer else values[i]
            set_at = start + DRIFT_BASELINE_MINUTES
        difference = values[i] - baseline
        up = max(0.0, up + (difference - k) * step)
        down = max(0.0, down + (-difference - k) * step)
        alarm[i], drift[i], baseline_time[i] = up > h or down > h, difference, set_at
    origin = frame["timestamp"].iloc[0]
    baseline_at = pd.Series(origin + pd.to_timedelta(baseline_time, unit="min"), index=frame.index)
    return pd.Series(alarm, index=frame.index), pd.Series(drift, index=frame.index), baseline_at


def _flag(rows: list, rule: str, category: str, parameter: str, unit: str, severity: pd.Series, values: pd.Series,
          detail: dict[str, Any] | None = None, **extra: pd.Series) -> None:
    """Append one rule's flagged readings (severity > 0) to ``rows``."""
    hit = severity.fillna(0) > 0
    if not hit.any():
        return
    part = pd.DataFrame({"row": np.flatnonzero(hit.to_numpy()), "severity": severity[hit].astype(int).to_numpy(),
                         "value": values[hit].to_numpy(dtype=float)})
    for name, series in extra.items():
        part[name] = series[hit].to_numpy()
    part["rule"], part["category"], part["parameter"], part["unit"] = rule, category, parameter, unit
    part["detail"] = [detail or {}] * len(part)
    rows.append(part)


def flag_readings(frame: pd.DataFrame, twin: dict[str, dict[str, Any]], drift: bool = True) -> pd.DataFrame:
    """Every flagged reading, one row per (reading, rule).

    ``frame`` is the prepared prediction frame (with ``annulus_glitch`` and ``<target>_missing`` flags).
    ``twin`` maps a target column to ``{"label", "unit", "predicted", "band"}``, where ``predicted`` holds
    each reading's prediction from a model that never saw that reading's recording period. ``drift=False``
    leaves out the gradual-drift check (used to measure what it adds).
    """
    rows: list[pd.DataFrame] = []
    injecting = frame["flow_bpm"] > 1.0
    none = pd.Series(0, index=frame.index)

    # 1. Sensor faults.
    _flag(rows, "annulus_glitch", "sensor", "Annulus pressure", "psi",
          none.mask(frame["annulus_glitch"], WARNING), frame["annulus_raw"], {"limit": ANNULUS_MAX_PSI})
    for column, name in [("corrected_bhp", "CBHP"), ("bht", "BHT")]:
        _flag(rows, f"{column}_missing", "sensor", name, "", none.mask(frame[f"{column}_missing"], WARNING), none)
    low_cbhp = (frame["corrected_bhp"] < CBHP_MIN_REAL_PSI) & ~frame["corrected_bhp_missing"]
    _flag(rows, "corrected_bhp_not_real", "sensor", "CBHP", "psi", none.mask(low_cbhp, WARNING), frame["corrected_bhp"],
          {"limit": CBHP_MIN_REAL_PSI})
    gap = frame.groupby("period")["timestamp"].diff().dt.total_seconds().div(60)
    _flag(rows, "logger_gap", "sensor", "Data logger", "min", none.mask(gap > LOGGER_GAP_MINUTES, WARNING), gap)
    for column, name in STUCK_COLUMNS.items():
        unchanged = _minutes_unchanged(frame, column)
        stuck = (unchanged >= STUCK_MINUTES) & injecting
        if f"{column}_missing" in frame:
            stuck &= ~frame[f"{column}_missing"]
        _flag(rows, f"{column}_stuck", "sensor", name, "min", none.mask(stuck, WARNING), unchanged)

    # 2. Operating limits.
    for column, label, unit, (warn_high, crit_high), (warn_low, crit_low), low_injecting_only in LIMIT_RULES:
        value = frame[column]
        valid = injecting.copy() if column in INJECTING_ONLY_COLUMNS else pd.Series(True, index=frame.index)
        if f"{column}_missing" in frame:
            valid &= ~frame[f"{column}_missing"]
        if column == "pump_speed":
            valid &= frame["pump_speed_estimated"] == 0  # estimated from flow in period 1, not a real reading
        high = none.copy()
        if warn_high is not None:
            high = high.mask(value > warn_high, WARNING)
        if crit_high is not None:
            high = high.mask(value > crit_high, CRITICAL)
        _flag(rows, f"{column}_high", "limit", label, unit, high.where(valid, 0), value,
              {"warning": warn_high, "critical": crit_high, "direction": "high", "column": column})
        low = none.copy()
        if warn_low is not None:
            low = low.mask(value < warn_low, WARNING)
        if crit_low is not None:
            low = low.mask(value < crit_low, CRITICAL)
        if low_injecting_only:
            low = low.where(injecting, 0)
        _flag(rows, f"{column}_low", "limit", label, unit, low.where(valid, 0), value,
              {"warning": warn_low, "critical": crit_low, "direction": "low", "column": column})

    # 3. Rates of change.
    bht_change = frame["bht"] - _minutes_ago(frame, "bht", BHT_DROP_MINUTES)
    bht_drop = (bht_change < -BHT_DROP_F) & injecting & (frame["minutes_injecting"] >= BHT_DROP_AFTER_INJECTING_MINUTES)
    _flag(rows, "bht_drop", "rate", "Bottom-hole temperature", "°F", none.mask(bht_drop, WARNING), bht_change,
          {"limit": BHT_DROP_F, "minutes": BHT_DROP_MINUTES})
    annulus_change = frame["annulus_psi"] - _minutes_ago(frame, "annulus_psi", ANNULUS_CHANGE_MINUTES)
    flow_change = frame["flow_bpm"] - _minutes_ago(frame, "flow_bpm", ANNULUS_CHANGE_MINUTES)
    annulus_jump = (annulus_change.abs() > ANNULUS_CHANGE_PSI) & (flow_change.abs() < ANNULUS_FLOW_STEADY_BPM)
    _flag(rows, "annulus_change", "rate", "Annulus pressure", "psi", none.mask(annulus_jump, WARNING), annulus_change,
          {"limit": ANNULUS_CHANGE_PSI, "minutes": ANNULUS_CHANGE_MINUTES})

    # 4. Model mismatch (digital-twin residual).
    steady = injecting & (frame["minutes_injecting"] >= MODEL_AFTER_INJECTING_MINUTES)
    for column, spec in twin.items():
        band = spec.get("band")
        predicted = pd.Series(spec["predicted"], index=frame.index)
        if not band or predicted.isna().all():
            continue
        residual = frame[column] - predicted
        sustained = _trailing_median(frame, residual.abs(), MODEL_SMOOTHING)
        check = steady & ~frame[f"{column}_missing"] & predicted.notna()
        severity = none.mask(check & (sustained > band), WARNING).mask(check & (sustained > MODEL_CRITICAL_BANDS * band), CRITICAL)
        _flag(rows, f"{column}_model", "model", spec["label"].capitalize(), spec["unit"], severity, frame[column],
              {"band": float(band)}, expected=predicted, residual=residual)

        # 5. Gradual drift (CUSUM on the same gap).
        if drift:
            alarm, change, baseline_at = _cusum_drift(
                frame, _trailing_median(frame, residual, DRIFT_SMOOTHING), steady, check, float(band)
            )
            _flag(rows, f"{column}_drift", "drift", spec["label"].capitalize(), spec["unit"],
                  none.mask(alarm, WARNING), frame[column],
                  {"band": float(band), "k": DRIFT_K_BANDS * float(band)}, drift=change, baseline_at=baseline_at)

    if not rows:
        return pd.DataFrame(columns=["row", "severity", "value", "rule", "category", "parameter", "unit", "detail"])
    flagged = pd.concat(rows, ignore_index=True)
    flagged["timestamp"] = frame["timestamp"].to_numpy()[flagged["row"].to_numpy()]
    flagged["period"] = frame["period"].to_numpy()[flagged["row"].to_numpy()]
    return flagged.sort_values(["timestamp", "rule"]).reset_index(drop=True)


def _fmt(value: float, unit: str = "") -> str:
    decimals = 0 if abs(value) >= 1000 else 1 if abs(value) >= 10 else 2
    text = f"{value:,.{decimals}f}"
    return f"{text} {unit}".strip()


def _describe(group: pd.DataFrame, severity: int) -> tuple[str, str]:
    """Message and recommended action for one event."""
    first = group.iloc[0]
    rule, unit, detail, name = first["rule"], first["unit"], first["detail"], first["parameter"]
    if rule == "annulus_glitch":
        return (
            f"Annulus gauge read {_fmt(group['value'].max(), unit)}, which is not physically possible "
            f"(above {_fmt(detail['limit'], unit)}). The models use the previous valid reading instead.",
            "Check the annulus pressure sensor and its wiring.",
        )
    if rule.endswith("_missing"):
        return f"No {name} reading was recorded.", f"Check the {name} gauge and the data logger."
    if rule == "corrected_bhp_not_real":
        return (
            f"CBHP read {_fmt(group['value'].min(), unit)}, below {_fmt(detail['limit'], unit)}, which is not a real "
            "reservoir pressure (gauge pulled or moved, or logger stopped).",
            "Treat as missing data, not a pressure alarm; confirm the gauge position.",
        )
    if rule == "logger_gap":
        return (
            f"The data logger recorded nothing for {group['value'].max():,.0f} minutes.",
            "Check the data logger and its communication link.",
        )
    if rule.endswith("_stuck"):
        return (
            f"The {name} reading stayed exactly the same for {group['value'].max():,.0f} minutes while injecting.",
            f"The {name} sensor may be frozen; compare it with the related sensors.",
        )
    if first["category"] == "limit":
        direction = detail["direction"]
        peak = group["value"].max() if direction == "high" else group["value"].min()
        limit = detail["critical"] if severity == CRITICAL else detail["warning"]
        word = "above" if direction == "high" else "below"
        level = "critical limit" if severity == CRITICAL else "normal limit"
        action = LIMIT_ACTIONS.get((detail["column"], direction, severity)) or DEFAULT_ACTIONS[severity]
        return f"{name} reached {_fmt(peak, unit)}, {word} the {level} of {_fmt(limit, unit)}.", action
    if rule == "bht_drop":
        return (
            f"BHT fell {abs(group['value'].min()):,.1f} °F within {detail['minutes']} minutes after more than an hour "
            "of steady injection.",
            "Investigate a possible cold-CO2 front or thermal-stress event; compare with flow rate and surface temperature.",
        )
    if rule == "annulus_change":
        change = group.loc[group["value"].abs().idxmax(), "value"]
        return (
            f"Annulus pressure changed {change:+,.0f} psi within {detail['minutes']} minutes while the flow rate was steady.",
            "Possible tubing or packer leak: compare annulus and tubing pressure and confirm well integrity.",
        )
    if first["category"] == "drift":
        worst = group.loc[group["drift"].abs().idxmax()]
        side = "above" if worst["drift"] > 0 else "below"
        message = (
            f"{name} has drifted {_fmt(abs(worst['drift']), unit)} {side} its usual relation to the surface readings "
            f"(baseline set at {pd.Timestamp(first['baseline_at']):%d %b %H:%M})."
        )
        if abs(worst["drift"]) < detail["band"]:
            message += (
                f" The change built up gradually and is still within the ±{_fmt(detail['band'], unit)} model band, "
                "so the model check would not show it yet."
            )
        return message, (
            "Check the gauge calibration. If the reading is real, look for a gradual downhole change such as "
            "near-wellbore pressure build-up, reduced injectivity or a developing leak."
        )
    worst = group.loc[group["residual"].abs().idxmax()]
    side = "above" if worst["residual"] > 0 else "below"
    return (
        f"{name} measured {_fmt(worst['value'], unit)} while the surface readings predict {_fmt(worst['expected'], unit)}: "
        f"{_fmt(abs(worst['residual']), unit)} {side} the model, beyond its ±{_fmt(detail['band'], unit)} error band. "
        "The bottom-hole reading is not explained by the surface conditions.",
        "Confirm the gauge reading; if it is real, look for a downhole change (leak, plugging, cold front) "
        "that the surface readings do not show.",
    )


def alerts_until(flagged: pd.DataFrame, at: pd.Timestamp, latest_reading: pd.Timestamp) -> list[dict[str, Any]]:
    """Group the readings flagged up to ``at`` into events, newest first."""
    seen = flagged[flagged["timestamp"] <= at]
    events = []
    for rule, part in seen.groupby("rule", sort=False):
        merge = pd.Timedelta(minutes=MERGE_MINUTES[part["category"].iloc[0]])
        new_event = (
            (part["timestamp"].diff() > merge) | (part["period"] != part["period"].shift())
        ).cumsum()
        for _, group in part.groupby(new_event):
            start, end = group["timestamp"].min(), group["timestamp"].max()
            duration = (end - start).total_seconds() / 60
            category = group["category"].iloc[0]
            if duration < MIN_MINUTES[category]:
                continue
            severity = int(group["severity"].max())
            message, action = _describe(group, severity)
            events.append(
                {
                    "rule": rule,
                    "category": CATEGORIES[category],
                    "parameter": group["parameter"].iloc[0],
                    "severity": SEVERITY_NAMES[severity],
                    "start": start.isoformat(),
                    "end": end.isoformat(),
                    "duration_minutes": round(duration, 1),
                    "readings": int(len(group)),
                    "active": bool((latest_reading - end).total_seconds() / 60 <= ACTIVE_WITHIN_MINUTES),
                    "message": message,
                    "action": action,
                }
            )
    return sorted(events, key=lambda event: event["start"], reverse=True)


def rules_summary() -> list[dict[str, str]]:
    """Plain-language description of each check, for the dashboard."""
    return [
        {"category": CATEGORIES["sensor"], "rule": (
            f"Impossible readings (annulus above {ANNULUS_MAX_PSI:,.0f} psi, CBHP below {CBHP_MIN_REAL_PSI:,.0f} psi), "
            f"missing gauge readings, logger gaps over {LOGGER_GAP_MINUTES:g} min, or a gauge stuck on one value for "
            f"{STUCK_MINUTES:g} min while injecting.")},
        {"category": CATEGORIES["limit"], "rule": (
            "Warning and critical levels from the CO2 Injection Knowledge Base for CBHP, BHT, surface pressure and "
            "temperature, annulus pressure, flow rate, pump speed and pump-inlet conditions. Low-reading limits apply "
            f"while injecting only. Raised after {MIN_MINUTES['limit']:g} min.")},
        {"category": CATEGORIES["rate"], "rule": (
            f"BHT falling more than {BHT_DROP_F:g} °F in {BHT_DROP_MINUTES} min after the first hour of injection, or "
            f"annulus pressure changing more than {ANNULUS_CHANGE_PSI:,.0f} psi in {ANNULUS_CHANGE_MINUTES} min while the "
            "flow rate is steady.")},
        {"category": CATEGORIES["model"], "rule": (
            f"The measured CBHP or BHT differs from the model's prediction (from the surface readings) by more than "
            f"the model's 90% error band on unseen periods, as a {MODEL_SMOOTHING.replace('min', '-min')} median, "
            f"for {MIN_MINUTES['model']:g} min or more, after the first hour of injection. Critical beyond "
            f"{MODEL_CRITICAL_BANDS:g}× the band.")},
        {"category": CATEGORIES["drift"], "rule": (
            "A CUSUM (cumulative sum) of the same model gap, for slow changes that have not reached the error band. "
            f"Its baseline is the gap's median over the first {DRIFT_BASELINE_MINUTES:g} min of each steady-injection "
            f"stretch; every minute the gap differs from it by more than {DRIFT_K_BANDS:g}× the band adds the excess "
            f"to the sum, and an alert is raised when the sum passes {DRIFT_H_BAND_MINUTES:g}× the band (in unit-minutes).")},
        {"category": "Grouping", "rule": (
            "Readings flagged by the same check within "
            + ", ".join(f"{minutes:g} min ({CATEGORIES[key].lower()})" for key, minutes in MERGE_MINUTES.items())
            + " of each other count as one alert. An alert is active while its last flagged reading is within "
            f"{ACTIVE_WITHIN_MINUTES:g} min of the latest reading.")},
    ]
