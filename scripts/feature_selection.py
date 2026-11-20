"""Reproduce and compare the feature selection for the CBHP and BHT models.

Every feature set is scored the way the deployed models are chosen: leave-one-period-out (each recording
period predicted by a model trained on the other two), Gradient Boosting, injecting readings scored, with the
same output smoothing the app uses. The score is the MAE averaged over the three periods (the selection
criterion), plus R² pooled over all held-out readings.

Compared:
  * CBHP candidate sets: 14 engineered features, 9 raw surface readings (deployed), 7 raw readings without
    pump speed and calculated flow (both redundant with flow rate).
  * CBHP recursive feature elimination (wrapper) on the 9 raw readings, removing at each step the feature with the
    lowest permutation importance measured on the held-out periods.
  * Embedded methods for both targets, selected inside each fold from the training periods only:
    Gradient Boosting importance (SelectFromModel, threshold = mean and median) and Lasso (non-zero
    coefficients on standardised inputs), each followed by Gradient Boosting on the selected features.

Note: the wrapper choices were made using all three periods, so their scores are slightly optimistic compared
with the embedded methods, which never see the held-out period when selecting.

Usage (from the project folder, with PostgreSQL running):
    python scripts/feature_selection.py
Results are printed and written to docs/results/feature_selection.md.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.feature_selection import SelectFromModel
from sklearn.inspection import permutation_importance
from sklearn.linear_model import LassoCV
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import SessionLocal  # noqa: E402
from app.services import prediction as p  # noqa: E402
from app.services.fulldata import full_data_rows  # noqa: E402

OUTPUT = Path(__file__).resolve().parents[1] / "docs" / "results" / "feature_selection.md"
PERMUTATION_REPEATS = 3
SEED = 42


def model():
    return GradientBoostingRegressor(random_state=SEED)


def score(frame: pd.DataFrame, target: str, choose) -> dict:
    """Leave-one-period-out score. ``choose(train)`` returns the feature list for that fold."""
    maes, residuals, actuals, chosen = [], [], [], []
    for period in sorted(frame["period"].unique()):
        train, held_out = frame[frame["period"] != period], frame[frame["period"] == period]
        injecting = (held_out["injecting"] == 1).to_numpy()
        if injecting.sum() < 2:
            continue
        features = list(choose(train))
        chosen.append(features)
        fitted = model().fit(train[features], train[target])
        predicted = p._smooth_predictions(held_out, fitted.predict(held_out[features]), target)[injecting]
        actual = held_out[target].to_numpy()[injecting]
        maes.append(float(np.mean(np.abs(actual - predicted))))
        residuals.append(actual - predicted)
        actuals.append(actual)
    residuals, actuals = np.concatenate(residuals), np.concatenate(actuals)
    return {
        "mae": float(np.mean(maes)),
        "r2": p._pooled_r2(residuals, actuals),
        "features": chosen,
    }


def fixed(features):
    return lambda train: features


def tree_importance(pool, threshold):
    def choose(train):
        selector = SelectFromModel(model(), threshold=threshold).fit(train[pool], train[TARGET])
        return [f for f, keep in zip(pool, selector.get_support()) if keep]
    return choose


def lasso(pool):
    def choose(train):
        pipeline = make_pipeline(StandardScaler(), LassoCV(cv=5, random_state=SEED, max_iter=20000))
        pipeline.fit(train[pool], train[TARGET])
        coefficients = pipeline[-1].coef_
        kept = [f for f, c in zip(pool, coefficients) if abs(c) > 1e-8]
        return kept or pool
    return choose


def held_out_permutation_importance(frame, target, features) -> dict[str, float]:
    """Mean permutation importance (rise in MAE) measured on each held-out period's injecting readings."""
    totals = dict.fromkeys(features, 0.0)
    periods = sorted(frame["period"].unique())
    for period in periods:
        train, held_out = frame[frame["period"] != period], frame[frame["period"] == period]
        test = held_out[held_out["injecting"] == 1]
        fitted = model().fit(train[features], train[target])
        result = permutation_importance(fitted, test[features], test[target], n_repeats=PERMUTATION_REPEATS,
                                        random_state=SEED, scoring="neg_mean_absolute_error")
        for feature, value in zip(features, result.importances_mean):
            totals[feature] += value / len(periods)
    return totals


def recursive_elimination(frame, target, features):
    """Backward elimination by held-out permutation importance; scores every subset size."""
    remaining, path = list(features), []
    while remaining:
        result = score(frame, target, fixed(remaining))
        importance = held_out_permutation_importance(frame, target, remaining) if len(remaining) > 1 else {}
        weakest = min(importance, key=importance.get) if importance else None
        path.append({"size": len(remaining), "mae": result["mae"], "r2": result["r2"], "removed_next": weakest})
        print(f"  RFE {len(remaining):2d} features: MAE {result['mae']:.2f}, R² {result['r2']:.3f}; weakest: {weakest}")
        if weakest is None:
            break
        remaining.remove(weakest)
    return path


def feature_counts(chosen: list[list[str]]) -> str:
    sizes = sorted({len(f) for f in chosen})
    return "–".join(str(s) for s in (sizes[0], sizes[-1])) if len(sizes) > 1 else str(sizes[0])


def markdown_table(rows: list[dict]) -> str:
    columns = list(rows[0])
    lines = ["| " + " | ".join(columns) + " |", "|" + "|".join("---" for _ in columns) + "|"]
    lines += ["| " + " | ".join(str(row[c]) for c in columns) + " |" for row in rows]
    return "\n".join(lines)


def main() -> None:
    global TARGET
    db = SessionLocal()
    try:
        frame = p._prepare_frame(full_data_rows(db))
    finally:
        db.close()
    raw_without_pump = [f for f in p.RAW_FEATURES if f not in {"pump_speed", "calc_flow_from_pump_speed"}]
    pools = {
        "corrected_bhp": list(dict.fromkeys(p.RAW_FEATURES + p.HISTORY_FEATURES)),
        "bht": list(dict.fromkeys(p.BHT_ALL_FEATURES + ["pump_speed", "calc_flow_from_pump_speed"])),
    }
    candidates = {
        "corrected_bhp": [
            ("Wrapper: 9 raw surface readings (deployed)", p.CBHP_FEATURES),
            ("14 engineered features (surface + history)", p.FEATURES),
            ("7 raw readings, no pump speed / calc. flow", raw_without_pump),
        ],
        "bht": [
            ("Wrapper: RFE + group ablation, 20 features (deployed)", p.BHT_FEATURES),
            ("All 27 engineered features", p.BHT_ALL_FEATURES),
        ],
    }
    units = {"corrected_bhp": "psi", "bht": "°F"}
    lines = ["# Feature selection comparison", "",
             "Gradient Boosting, leave-one-period-out on injecting readings. MAE = mean over the 3 unseen periods "
             "(the selection criterion); R² pooled over all held-out readings. Embedded methods select inside each "
             "fold from the training periods only; wrapper choices were made on all periods, so they are slightly "
             "optimistic.", ""]
    for target in ("corrected_bhp", "bht"):
        TARGET = target
        pool = pools[target]
        label = "CBHP" if target == "corrected_bhp" else "BHT"
        print(f"\n== {label} (candidate pool: {len(pool)} features)")
        rows = []
        methods = [(name, "Wrapper / set comparison", fixed(features)) for name, features in candidates[target]]
        methods += [
            (f"Tree importance ≥ mean, from {len(pool)}", "Embedded", tree_importance(pool, "mean")),
            (f"Tree importance ≥ median, from {len(pool)}", "Embedded", tree_importance(pool, "median")),
            (f"Lasso (non-zero coefficients), from {len(pool)}", "Embedded", lasso(pool)),
        ]
        for name, kind, choose in methods:
            result = score(frame, target, choose)
            rows.append({"Method": name, "Type": kind, "Features": feature_counts(result["features"]),
                         f"MAE ({units[target]})": f"{result['mae']:.2f}", "R²": f"{result['r2']:.3f}"})
            print(f"  {name:55s} {rows[-1]['Features']:>5s} features  MAE {result['mae']:.2f}  R² {result['r2']:.3f}")
            if kind == "Embedded":
                kept = sorted(set().union(*result["features"]))
                print(f"     selected (any fold): {kept}")
        lines += [f"## {label}", "", markdown_table(rows), ""]
        if target == "corrected_bhp":
            print("  Recursive elimination on the 9 raw readings:")
            path = recursive_elimination(frame, target, p.CBHP_FEATURES)
            lines += ["### CBHP recursive feature elimination (9 raw readings)", "",
                      "Each step removes the feature with the lowest permutation importance on the held-out periods.",
                      "", markdown_table([{"Features": s["size"], "MAE (psi)": f"{s['mae']:.2f}", "R²": f"{s['r2']:.3f}",
                                           "Removed next": s["removed_next"] or "-"} for s in path]), ""]
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nWritten to {OUTPUT}")


TARGET = "corrected_bhp"

if __name__ == "__main__":
    main()
