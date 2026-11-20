# Feature selection comparison

Gradient Boosting, leave-one-period-out on injecting readings. MAE = mean over the 3 unseen periods (the selection criterion); R² pooled over all held-out readings. Embedded methods select inside each fold from the training periods only; wrapper choices were made on all periods, so they are slightly optimistic.

## CBHP

| Method | Type | Features | MAE (psi) | R² |
|---|---|---|---|---|
| Wrapper: 9 raw surface readings (deployed) | Wrapper / set comparison | 9 | 29.49 | 0.284 |
| 14 engineered features (surface + history) | Wrapper / set comparison | 14 | 35.45 | -0.074 |
| 7 raw readings, no pump speed / calc. flow | Wrapper / set comparison | 7 | 35.91 | 0.210 |
| Tree importance ≥ mean, from 16 | Embedded | 2–6 | 47.53 | -0.421 |
| Tree importance ≥ median, from 16 | Embedded | 8 | 36.76 | -0.047 |
| Lasso (non-zero coefficients), from 16 | Embedded | 6–11 | 34.29 | 0.149 |

### CBHP recursive feature elimination (9 raw readings)

Each step removes the feature with the lowest permutation importance on the held-out periods.

| Features | MAE (psi) | R² | Removed next |
|---|---|---|---|
| 9 | 29.49 | 0.284 | pressure_before_triplex |
| 8 | 31.71 | 0.270 | flow_bpm |
| 7 | 33.00 | 0.229 | pump_speed |
| 6 | 34.61 | 0.218 | calc_flow_from_pump_speed |
| 5 | 36.24 | 0.086 | temperature_before_triplex |
| 4 | 33.05 | 0.285 | flowrate_meter |
| 3 | 35.36 | 0.023 | annulus_psi |
| 2 | 39.91 | -0.163 | surface_temp |
| 1 | 39.72 | -0.151 | - |

## BHT

| Method | Type | Features | MAE (°F) | R² |
|---|---|---|---|---|
| Wrapper: RFE + group ablation, 20 features (deployed) | Wrapper / set comparison | 20 | 4.44 | 0.738 |
| All 27 engineered features | Wrapper / set comparison | 27 | 5.09 | 0.687 |
| Tree importance ≥ mean, from 29 | Embedded | 2–7 | 5.39 | 0.660 |
| Tree importance ≥ median, from 29 | Embedded | 15 | 5.15 | 0.671 |
| Lasso (non-zero coefficients), from 29 | Embedded | 4–23 | 5.66 | 0.644 |
