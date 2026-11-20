"""Evaluate the alert checks by injecting artificial gauge faults into clean recorded data.

The dataset has no labelled faults, so precision and recall cannot be measured directly. Instead, known
faults are added to the bottom-hole gauge readings (CBHP or BHT) at random times during steady injection,
the alert checks are run on the faulted data, and the script records whether a new alert was raised for that
gauge and how long it took. Alerts on the unmodified data give the false-alarm rate.

The surface readings are not changed, so the model predictions (made from the surface readings) stay the
same, exactly as they would if only the bottom-hole gauge were faulty.

Usage (from the project folder, with PostgreSQL running):
    python scripts/evaluate_alerts.py            # full evaluation with the current settings
    python scripts/evaluate_alerts.py --grid     # also compare CUSUM drift settings (k, h)
Results are printed and written to docs/results/alert_evaluation.md.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import SessionLocal  # noqa: E402
from app.services import alerts  # noqa: E402
from app.services import prediction  # noqa: E402

TRIALS = 30
SEED = 42
DETECT_WITHIN_MINUTES = 15  # an alert raised up to this long after the fault ends still counts
MIN_START_INJECTING_MINUTES = 120  # faults start once the drift baseline is set (60 min start-up + 30 min)
OUTPUT = Path(__file__).resolve().parents[1] / "docs" / "results" / "alert_evaluation.md"
TARGETS = {"corrected_bhp": "CBHP", "bht": "BHT"}


def markdown_table(table: pd.DataFrame, index: bool = False) -> str:
    """A DataFrame as a Markdown table (without needing the optional tabulate package)."""
    if index:
        table = table.reset_index()
    header = "| " + " | ".join(str(column) for column in table.columns) + " |"
    rule = "|" + "|".join("---" for _ in table.columns) + "|"
    body = ["| " + " | ".join(str(value) for value in row) + " |" for row in table.itertuples(index=False)]
    return "\n".join([header, rule, *body])


def fault_cases(bands: dict[str, float]) -> list[dict]:
    """Fault types and sizes for each gauge. Sizes are tied to the model error band, so both gauges are
    tested at comparable difficulty (CBHP band ±48 psi, BHT band ±7.4 °F)."""
    cases = []
    for target, band in bands.items():
        for per_hour in [0.25, 0.5, 1.0]:
            cases.append({"target": target, "kind": "drift", "size": per_hour * band, "minutes": 120,
                          "label": f"Slow drift {per_hour:g}× band per hour"})
        for times in [0.5, 1.0, 2.0]:
            cases.append({"target": target, "kind": "step", "size": times * band, "minutes": 60,
                          "label": f"Step offset {times:g}× band"})
        cases.append({"target": target, "kind": "stuck", "size": 0.0, "minutes": 30, "label": "Gauge stuck (frozen value)"})
        cases.append({"target": target, "kind": "spike", "size": 3 * band, "minutes": 5, "label": "Short spike 3× band, 5 min"})
    return cases


def inject(values: np.ndarray, minutes: np.ndarray, start: int, end: int, case: dict, sign: int) -> np.ndarray:
    """Return a copy of ``values`` with the fault applied to positions ``start``..``end`` (inclusive)."""
    faulted = values.copy()
    window = slice(start, end + 1)
    elapsed = minutes[window] - minutes[start]
    if case["kind"] == "drift":
        faulted[window] += sign * case["size"] * elapsed / 60
    elif case["kind"] in {"step", "spike"}:
        faulted[window] += sign * case["size"]
    elif case["kind"] == "stuck":
        faulted[window] = values[start]
    return faulted


def candidate_starts(frame: pd.DataFrame, minutes_needed: float) -> np.ndarray:
    """Positions where a fault of ``minutes_needed`` fits inside one steady-injection stretch."""
    steady = (frame["flow_bpm"] > 1.0) & (frame["minutes_injecting"] >= alerts.MODEL_AFTER_INJECTING_MINUTES)
    stretch = ((steady != steady.shift()) | (frame["period"] != frame["period"].shift())).cumsum()
    end_time = frame.groupby(stretch)["timestamp"].transform("max")
    room = (end_time - frame["timestamp"]).dt.total_seconds() / 60
    ok = steady & (frame["minutes_injecting"] >= MIN_START_INJECTING_MINUTES) & (room >= minutes_needed)
    return np.flatnonzero(ok.to_numpy())


def period_slices(frame: pd.DataFrame) -> dict[int, np.ndarray]:
    return {period: np.flatnonzero((frame["period"] == period).to_numpy()) for period in frame["period"].unique()}


def new_events(clean: pd.DataFrame, faulted: pd.DataFrame, target: str, until: pd.Timestamp, latest: pd.Timestamp):
    """Alert events built only from flagged readings for ``target`` that the clean run did not have."""
    def keyed(flags):
        mine = flags[flags["rule"].str.startswith(f"{target}_")]  # includes bht_drop for BHT
        return mine, set(zip(mine["row"], mine["rule"]))

    _, clean_keys = keyed(clean)
    mine, _ = keyed(faulted)
    fresh = mine[[key not in clean_keys for key in zip(mine["row"], mine["rule"])]]
    return alerts.alerts_until(fresh, until, latest) if not fresh.empty else []


def run_case(frame, twin, case, rng, drift: bool, slices, clean_by_period):
    """Detection rate, delays and detecting checks for one fault case over TRIALS random start times."""
    target = case["target"]
    starts = candidate_starts(frame, case["minutes"])
    if starts.size == 0:
        return None
    detected, delays, by = 0, [], {}
    for _ in range(TRIALS):
        start = int(rng.choice(starts))
        sign = int(rng.choice([-1, 1]))
        period = int(frame["period"].iloc[start])
        rows = slices[period]
        part = frame.iloc[rows].reset_index(drop=True)
        part_twin = {column: {**spec, "predicted": np.asarray(spec["predicted"])[rows]} for column, spec in twin.items()}
        local_start = int(np.searchsorted(rows, start))
        minutes = ((part["timestamp"] - part["timestamp"].iloc[0]).dt.total_seconds() / 60).to_numpy()
        fault_end_time = part["timestamp"].iloc[local_start] + pd.Timedelta(minutes=case["minutes"])
        local_end = int(np.searchsorted(part["timestamp"].to_numpy(), fault_end_time.to_datetime64(), side="right")) - 1
        part[target] = inject(part[target].to_numpy(dtype=float), minutes, local_start, local_end, case, sign)
        faulted = alerts.flag_readings(part, part_twin, drift=drift)
        fault_start = part["timestamp"].iloc[local_start]
        until = part["timestamp"].iloc[local_end] + pd.Timedelta(minutes=DETECT_WITHIN_MINUTES)
        events = [
            event for event in new_events(clean_by_period[(period, drift)], faulted, target, until, part["timestamp"].iloc[-1])
            if pd.Timestamp(event["start"]) >= fault_start
        ]
        if not events:
            continue
        category_key = {name: key for key, name in alerts.CATEGORIES.items()}
        raised = [
            (pd.Timestamp(event["start"]) + pd.Timedelta(minutes=alerts.MIN_MINUTES[category_key[event["category"]]]), event["category"])
            for event in events
        ]
        first_time, first_check = min(raised)
        detected += 1
        delays.append((first_time - fault_start).total_seconds() / 60)
        by[first_check] = by.get(first_check, 0) + 1
    return {
        "detected": detected,
        "rate": detected / TRIALS,
        "median_delay": float(np.median(delays)) if delays else None,
        "first_check": max(by, key=by.get) if by else "-",
    }


def clean_runs(frame, twin, slices):
    """Flags on the unmodified data per period, with and without the drift check."""
    runs = {}
    for period, rows in slices.items():
        part = frame.iloc[rows].reset_index(drop=True)
        part_twin = {column: {**spec, "predicted": np.asarray(spec["predicted"])[rows]} for column, spec in twin.items()}
        for drift in (True, False):
            runs[(period, drift)] = alerts.flag_readings(part, part_twin, drift=drift)
    return runs


def false_alarms(frame, twin) -> tuple[pd.DataFrame, float]:
    """Alerts on the clean data for the bottom-hole gauges, per category, and the hours of steady injection."""
    flags = alerts.flag_readings(frame, twin)
    events = pd.DataFrame(alerts.alerts_until(flags, frame["timestamp"].iloc[-1], frame["timestamp"].iloc[-1]))
    steady = (frame["flow_bpm"] > 1.0) & (frame["minutes_injecting"] >= 60)
    step = frame.groupby("period")["timestamp"].diff().dt.total_seconds().div(60).fillna(0).clip(upper=1)
    hours = float(step[steady].sum() / 60)
    gauges = events[events["rule"].str.startswith(("corrected_bhp_", "bht_"))]
    return gauges, hours


def drift_grid(frame, twin, bands) -> pd.DataFrame:
    """Drift-only comparison of CUSUM settings: clean-data drift alarms against slow-drift detection."""
    steady = (frame["flow_bpm"] > 1.0) & (frame["minutes_injecting"] >= 60)
    results = []
    for k in [0.25, 0.5, 0.75]:
        for h in [5.0, 10.0, 20.0]:
            alerts.DRIFT_K_BANDS, alerts.DRIFT_H_BAND_MINUTES = k, h
            row = {"k (× band)": k, "h (× band·min)": h}
            clean_hours = 0.0
            for target, band in bands.items():
                predicted = pd.Series(np.asarray(twin[target]["predicted"]), index=frame.index)
                valid = steady & ~frame[f"{target}_missing"] & predicted.notna()
                gap = alerts._trailing_median(frame, frame[target] - predicted, alerts.DRIFT_SMOOTHING)
                alarm, _, _ = alerts._cusum_drift(frame, gap, steady, valid, band)
                step = frame.groupby("period")["timestamp"].diff().dt.total_seconds().div(60).fillna(0).clip(upper=1)
                clean_hours += float(step[alarm].sum() / 60)
                rng = np.random.default_rng(SEED)
                starts = candidate_starts(frame, 120)
                minutes = ((frame["timestamp"] - frame["timestamp"].iloc[0]).dt.total_seconds() / 60).to_numpy()
                for per_hour in [0.25, 0.5, 1.0]:
                    hits, delays = 0, []
                    for _ in range(TRIALS):
                        start, sign = int(rng.choice(starts)), int(rng.choice([-1, 1]))
                        end = int(np.searchsorted(minutes, minutes[start] + 120, side="right")) - 1
                        faulted = inject(frame[target].to_numpy(dtype=float), minutes, start, end,
                                         {"kind": "drift", "size": per_hour * band}, sign)
                        fgap = alerts._trailing_median(frame, pd.Series(faulted, index=frame.index) - predicted,
                                                       alerts.DRIFT_SMOOTHING)
                        falarm, _, _ = alerts._cusum_drift(frame, fgap, steady, valid, band)
                        new = falarm.to_numpy() & ~alarm.to_numpy()
                        hit = np.flatnonzero(new[start:end + 1])
                        if hit.size:
                            hits += 1
                            delays.append(minutes[start + hit[0]] - minutes[start])
                    row[f"{TARGETS[target]} {per_hour:g}×/h detected"] = f"{hits / TRIALS:.0%}"
                    row[f"{TARGETS[target]} {per_hour:g}×/h delay"] = f"{np.median(delays):.0f}" if delays else "-"
            row["Clean-data drift alarm (h)"] = round(clean_hours, 1)
            results.append(row)
    return pd.DataFrame(results)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--grid", action="store_true", help="also compare CUSUM drift settings")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        prediction.analyze_fulldata(db)
    finally:
        db.close()
    frame = prediction._analysis_cache["frame"]
    artifacts = prediction._analysis_cache["artifacts"]
    twin = {target: artifacts[key]["twin"] for key, (target, _) in prediction.TARGETS.items()}
    bands = {target: float(spec["band"]) for target, spec in twin.items()}
    settings = (alerts.DRIFT_K_BANDS, alerts.DRIFT_H_BAND_MINUTES)
    lines = ["# Alert evaluation with injected faults", "",
             f"{TRIALS} random start times per fault, during steady injection (at least {MIN_START_INJECTING_MINUTES} min "
             f"after injection started). A fault counts as detected if a new alert for that gauge is raised before "
             f"the fault ends or within {DETECT_WITHIN_MINUTES} min after. Delay = minutes from the fault starting to "
             "the alert being raised (median of detected trials). Error bands: "
             + ", ".join(f"{TARGETS[t]} ±{b:.1f}" for t, b in bands.items()) + ".", ""]

    if args.grid:
        grid = drift_grid(frame, twin, bands)
        alerts.DRIFT_K_BANDS, alerts.DRIFT_H_BAND_MINUTES = settings
        lines += ["## CUSUM drift settings", "",
                  "Drift check only. Clean-data drift alarm = hours the drift alert is on in the unmodified data "
                  "(bottom-hole gauges together).", "", markdown_table(grid), ""]
        print(grid.to_string(index=False))

    gauges, hours = false_alarms(frame, twin)
    counts = gauges.groupby("category").agg(alerts=("rule", "size"), minutes=("duration_minutes", "sum"))
    counts["per 24 h of steady injection"] = (counts["alerts"] / hours * 24).round(1)
    lines += ["## Alerts on the clean data (bottom-hole gauges)", "",
              f"{hours:.1f} hours of steady injection. These are not all false alarms (the 25 Sep BHT drop is a real "
              "event), so they are an upper bound on the false-alarm rate.", "", markdown_table(counts, index=True), ""]
    print(counts.to_string())

    slices = period_slices(frame)
    clean_by_period = clean_runs(frame, twin, slices)
    rows = []
    for case in fault_cases(bands):
        result = {"Gauge": TARGETS[case["target"]], "Fault": case["label"]}
        for drift in (False, True):
            outcome = run_case(frame, twin, case, np.random.default_rng(SEED), drift, slices, clean_by_period)
            tag = "with drift check" if drift else "without drift check"
            result[f"Detected ({tag})"] = f"{outcome['rate']:.0%}" if outcome else "n/a"
            result[f"Delay min ({tag})"] = (
                f"{outcome['median_delay']:.0f}" if outcome and outcome["median_delay"] is not None else "-"
            )
            if drift:
                result["First check to alert"] = outcome["first_check"] if outcome else "-"
        rows.append(result)
        print(result)
    table = pd.DataFrame(rows)
    lines += ["## Detection of injected faults", "",
              f"Drift check settings: k = {settings[0]:g}× band, h = {settings[1]:g}× band·min.", "",
              markdown_table(table), ""]
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nWritten to {OUTPUT}")


if __name__ == "__main__":
    main()
