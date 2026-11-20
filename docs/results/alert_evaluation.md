# Alert evaluation with injected faults

30 random start times per fault, during steady injection (at least 120 min after injection started). A fault counts as detected if a new alert for that gauge is raised before the fault ends or within 15 min after. Delay = minutes from the fault starting to the alert being raised (median of detected trials). Error bands: CBHP ±48.1, BHT ±7.4.

## CUSUM drift settings

Drift check only. Clean-data drift alarm = hours the drift alert is on in the unmodified data (bottom-hole gauges together).

| k (× band) | h (× band·min) | CBHP 0.25×/h detected | CBHP 0.25×/h delay | CBHP 0.5×/h detected | CBHP 0.5×/h delay | CBHP 1×/h detected | CBHP 1×/h delay | BHT 0.25×/h detected | BHT 0.25×/h delay | BHT 0.5×/h detected | BHT 0.5×/h delay | BHT 1×/h detected | BHT 1×/h delay | Clean-data drift alarm (h) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 0.25 | 5.0 | 7% | 10 | 7% | 11 | 3% | 7 | 13% | 36 | 27% | 34 | 27% | 38 | 23.8 |
| 0.25 | 10.0 | 7% | 24 | 7% | 23 | 3% | 29 | 17% | 46 | 30% | 48 | 33% | 48 | 22.3 |
| 0.25 | 20.0 | 17% | 18 | 10% | 36 | 10% | 16 | 17% | 70 | 33% | 53 | 40% | 44 | 19.9 |
| 0.5 | 5.0 | 17% | 38 | 13% | 33 | 17% | 5 | 47% | 60 | 67% | 44 | 83% | 40 | 14.6 |
| 0.5 | 10.0 | 43% | 29 | 30% | 43 | 47% | 83 | 40% | 80 | 60% | 56 | 87% | 52 | 12.2 |
| 0.5 | 20.0 | 50% | 61 | 43% | 48 | 73% | 38 | 27% | 107 | 50% | 74 | 87% | 80 | 4.8 |
| 0.75 | 5.0 | 50% | 92 | 43% | 57 | 100% | 97 | 33% | 103 | 73% | 66 | 97% | 58 | 0.5 |
| 0.75 | 10.0 | 30% | 114 | 40% | 71 | 100% | 109 | 0% | - | 50% | 83 | 87% | 62 | 0.0 |
| 0.75 | 20.0 | 0% | - | 40% | 95 | 47% | 61 | 0% | - | 37% | 100 | 57% | 68 | 0.0 |

## Alerts on the clean data (bottom-hole gauges)

18.7 hours of steady injection. These are not all false alarms (the 25 Sep BHT drop is a real event), so they are an upper bound on the false-alarm rate.

| category | alerts | minutes | per 24 h of steady injection |
|---|---|---|---|
| Gradual drift | 2 | 44.2 | 2.6 |
| Model mismatch | 9 | 126.7 | 11.6 |
| Operating limit | 9 | 452.2 | 11.6 |
| Rate of change | 2 | 49.3 | 2.6 |
| Sensor fault | 3 | 7.4 | 3.9 |

## Detection of injected faults

Drift check settings: k = 0.75× band, h = 5× band·min.

| Gauge | Fault | Detected (without drift check) | Delay min (without drift check) | Detected (with drift check) | Delay min (with drift check) | First check to alert |
|---|---|---|---|---|---|---|
| CBHP | Slow drift 0.25× band per hour | 13% | 23 | 50% | 90 | Gradual drift |
| CBHP | Slow drift 0.5× band per hour | 57% | 105 | 93% | 59 | Model mismatch |
| CBHP | Slow drift 1× band per hour | 100% | 61 | 100% | 39 | Model mismatch |
| CBHP | Step offset 0.5× band | 20% | 3 | 57% | 16 | Gradual drift |
| CBHP | Step offset 1× band | 67% | 3 | 100% | 4 | Model mismatch |
| CBHP | Step offset 2× band | 100% | 3 | 100% | 3 | Model mismatch |
| CBHP | Gauge stuck (frozen value) | 100% | 10 | 100% | 10 | Sensor fault |
| CBHP | Short spike 3× band, 5 min | 100% | 1 | 100% | 1 | Operating limit |
| BHT | Slow drift 0.25× band per hour | 10% | 95 | 33% | 104 | Gradual drift |
| BHT | Slow drift 0.5× band per hour | 80% | 94 | 87% | 83 | Gradual drift |
| BHT | Slow drift 1× band per hour | 100% | 45 | 100% | 43 | Rate of change |
| BHT | Step offset 0.5× band | 30% | 61 | 57% | 28 | Gradual drift |
| BHT | Step offset 1× band | 100% | 1 | 100% | 1 | Operating limit |
| BHT | Step offset 2× band | 100% | 1 | 100% | 1 | Operating limit |
| BHT | Gauge stuck (frozen value) | 100% | 10 | 100% | 10 | Sensor fault |
| BHT | Short spike 3× band, 5 min | 100% | 1 | 100% | 1 | Operating limit |
