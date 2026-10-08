# CO2 Injection Operating Thresholds and Safety Guidelines

Document ID: KB-CCS-001
Applies to: CCS Digital Twin — Injection Monitoring dashboard, Injection Optimization Simulator and AI Chatbot
Dataset: `fulldata` table (source workbook `combined_co2_data_only_file.xls`, sheet `Full`), 19–26 September 2009

## 1. Purpose and Scope

This document is the reference knowledge base used by the AI Chatbot (retrieval-augmented generation, RAG) to answer questions about CO2 injection threshold values, operating limits, alarm levels and recommended responses.

It contains three kinds of values. Always state which kind a value is when using it:

1. **Physical reference values** — fixed properties of CO2 (for example the critical point). These do not change between projects.
2. **Regulatory reference values** — rules from published regulations such as the US EPA Class VI well rules (40 CFR Part 146, Subpart H). The rules give ratios and requirements; the actual pressure numbers come from each site's permit.
3. **Project operating thresholds** — the Normal / Warning / Critical limits used by this digital twin. These are FYP design-basis values. They come from the simulator defaults and the operating ranges observed in the 2009 dataset. They are **not** values approved by a regulator or a well operator. A real project must replace them with limits from its permit, geomechanical study and well design.

Units follow the dashboard: pressures in psi, flow in barrels per minute (BPM), all temperatures (surface, before-triplex and bottom-hole) in °F.

## 2. Threshold Summary Table

Alarm levels used by the digital twin while CO2 is being injected (Flow BPM > 1.0). When the well is not injecting (Flow BPM ≤ 1.0), low readings are not alarms, but the upper Warning and Critical limits still apply. Readings below the Normal range are Warning unless a row says otherwise. They are never Critical.

| Parameter (dashboard name) | Normal | Warning | Critical | Basis |
|---|---|---|---|---|
| Corrected Bottom-Hole Pressure, CBHP (psi) | 1,071 – 1,980 | 1,980 – 2,200, or below 1,071 while injecting | > 2,200 | Max allowable CBHP 2,200 psi; 10% safety margin gives 1,980 psi; 1,071 psi = CO2 critical pressure |
| Bottom-Hole Pressure, BHP (psi) | 1,071 – 1,980 | 1,980 – 2,200 | > 2,200 | Same as CBHP; prefer CBHP for decisions |
| Bottom-Hole Temperature, BHT (°F) | 87.98 – 120 | 120 – 125, or below 87.98 while injecting | > 125 | 87.98 °F = CO2 critical temperature; observed 95th percentile ≈ 121.5 °F; maximum ≈ 125.5 °F |
| Surface (wellhead) injection pressure (psi) | ≤ 1,550 | 1,550 – 1,600 | > 1,600 | Maximum allowable surface injection pressure 1,600 psi |
| Annulus pressure (psi) | ≤ 2,000 | 2,000 – 2,500, or change > 200 psi in 10 min | > 2,500 | Annulus pressure change can mean a tubing or packer leak |
| Flow rate (BPM) | 1.0 – 4.9 | 4.9 – 5.0 | > 5.0 | Design maximum injection rate 5.0 BPM (≈ 210 GPM) |
| Pump speed (dashboard units) | ≤ 390 | 390 – 420 | > 420 | Normal running speed ≈ 361–377 |
| Pressure before triplex (pump suction, psi) | ≥ 220 and above CO2 saturation pressure + 20 psi | 200 – 220, or margin to saturation < 20 psi | < 200, or below saturation pressure | Prevent CO2 vaporising in the pump (cavitation) |
| Temperature before triplex (pump suction, °F) | ≤ 10 | 10 – 20 | > 20 | Warmer liquid CO2 has higher vapour pressure |

Physical and regulatory reference limits (not alarm levels):

| Item | Value | Type |
|---|---|---|
| CO2 critical temperature | 31.1 °C (87.98 °F) | Physical |
| CO2 critical pressure | 7.38 MPa (1,071 psi) | Physical |
| Maximum injection pressure in the injection zone (US EPA Class VI) | ≤ 90% of the fracture pressure of the injection zone | Regulatory |
| Confining zone (caprock) | Injection must not start new fractures or spread existing fractures in the confining zone | Regulatory |
| Annulus between tubing and long-string casing (US EPA Class VI) | Filled with non-corrosive fluid; annulus pressure kept above operating injection pressure unless the regulator decides otherwise | Regulatory |
| Automatic shut-off (US EPA Class VI) | Required to stop injection when monitored values go outside permitted limits | Regulatory |

## 3. Corrected Bottom-Hole Pressure (CBHP) Thresholds

CBHP is the bottom-hole pressure gauge reading after correction for gauge depth and drift. It is the main pressure used for safety decisions because it is closest to the pressure the reservoir and caprock feel.

- **Maximum allowable CBHP: 2,200 psi.** This is the default "Maximum allowable CBHP" in the Injection Optimization Simulator.
- **Design basis:** the project assumes an estimated injection-zone fracture pressure of about 2,445 psi. Applying the US EPA Class VI rule (injection pressure ≤ 90% of fracture pressure) gives 0.90 × 2,445 ≈ 2,200 psi.
- **Safe operating limit: 1,980 psi.** This applies a 10% safety margin to the maximum allowable CBHP (2,200 × 0.90). The simulator's "Safe Operation" mode uses this formula: safe limit = maximum allowable CBHP × (1 − safety margin %).
- **Lower limit: 1,071 psi.** Below the CO2 critical pressure, CO2 at the bottom of the well may not be in the dense supercritical phase. This is less efficient storage and can cause unstable two-phase flow.

Alarm levels for CBHP:

- Normal: 1,071 – 1,980 psi.
- Warning: 1,980 – 2,200 psi. Reduce the injection rate and watch the pressure trend.
- Critical: above 2,200 psi. Stop injection (shut-in) and inform the responsible engineer.
- Low pressure while injecting (100 – 1,071 psi with Flow BPM > 1.0): Warning (phase). CO2 may not be supercritical at the bottom of the well. This is not an overpressure risk, so it is never Critical; check the gauge, flow rate and CO2 supply.
- Low pressure while not injecting (Flow BPM ≤ 1.0): not an alarm. Pressure falls during shut-in, pump repairs and gauge work.
- Data quality: a reading below 100 psi is not a real reservoir pressure. It usually means the gauge was pulled out, moved for a temperature survey, or the logger stopped. Do not treat these values as pressure alarms; flag them as missing data.

Observed values in the dataset while injecting (Flow BPM > 1): median ≈ 1,857 psi, 99th percentile ≈ 1,976 psi, maximum ≈ 2,043 psi. Only about 0.2% of all records are above the 1,980 psi safe operating limit and none are above 2,200 psi.

## 4. Bottom-Hole Temperature (BHT) Thresholds

BHT shows how injected CO2 changes the temperature near the reservoir. Cold CO2 cools the near-wellbore rock. Large or fast temperature changes cause thermal stress on the casing, cement and rock.

All BHT values are in °F.

- **Supercritical check:** CO2 is supercritical only when the temperature is above 87.98 °F (31.1 °C) **and** the pressure is above 1,071 psi.
- **Lower limit: 87.98 °F.** While injecting, a BHT below the CO2 critical temperature means the CO2 at the bottom of the well is a cold liquid, not supercritical. This shows strong cooling by the injected CO2 and a higher risk of thermal stress. About 6.5% of BHT readings while injecting are below 87.98 °F.
- **Project maximum BHT: 125 °F.** This is about the highest value observed in the dataset (≈ 125.5 °F).
- **Warning level: 120 °F.** This is close to the observed 95th percentile while injecting (≈ 121.5 °F).
- **Rate of change:** a BHT drop of more than 5 °F in one hour during injection should be investigated as a possible cold-CO2 front or thermal-stress event.

Alarm levels for BHT:

- Normal: 87.98 – 120 °F.
- Warning: 120 – 125 °F, **or** below 87.98 °F while injecting (Flow BPM > 1.0). A low BHT is a cooling and phase warning, not an overheating risk, so it is never Critical.
- Critical: above 125 °F.
- Not injecting (Flow BPM ≤ 1.0): a BHT below 87.98 °F is not an alarm. The well warms back toward reservoir temperature after injection stops.

Observed values while injecting: 1st percentile ≈ 72 °F, median ≈ 113 °F, 95th percentile ≈ 121.5 °F, maximum ≈ 125.5 °F. The lowest value in the whole dataset is ≈ 56.7 °F.

Note about the simulator: the Injection Optimization Simulator's "Maximum allowable BHT" field defaults to 125 °F, the project maximum BHT.

## 5. Surface (Wellhead) Injection Pressure Thresholds

Surface pressure (Surface PSI) is the injection pressure at the wellhead after the triplex pump. Bottom-hole pressure is roughly surface pressure + pressure of the CO2 column in the well − friction losses in the tubing.

- **Maximum allowable surface injection pressure: 1,600 psi.** This keeps bottom-hole pressure below the 2,200 psi CBHP limit at the flow rates in this dataset.
- Normal: up to 1,550 psi.
- Warning: 1,550 – 1,600 psi. Do not raise the pump speed further.
- Critical: above 1,600 psi. Reduce the rate or stop the pump.

Observed values while injecting: median ≈ 1,453 psi, 99th percentile ≈ 1,538 psi, maximum ≈ 1,565 psi.

A sudden increase in surface pressure at a constant flow rate can mean blockage near the wellbore (for example salt precipitation or hydrate formation) or lower injectivity. A sudden decrease at constant flow rate can mean a leak or a new flow path, and must be investigated.

## 6. Annulus Pressure Thresholds and Well Integrity

The annulus is the space between the injection tubing and the casing. It is sealed by a packer at the bottom. Annulus pressure is the main sign of well (mechanical) integrity.

- **Regulatory reference (US EPA Class VI):** the annulus must be filled with a non-corrosive fluid, and the annulus pressure must be kept above the operating injection pressure unless the regulator decides this could harm well integrity. Continuous monitoring of injection pressure, rate, volume and annulus pressure is required.
- **This dataset:** annulus pressure is usually below surface injection pressure (median ≈ 1,314 psi versus ≈ 1,446 psi). So the digital twin uses absolute limits and rate-of-change alarms for the annulus, not the pressure-difference rule.

Alarm levels for annulus pressure:

- Normal: up to 2,000 psi with no sudden changes.
- Warning: 2,000 – 2,500 psi, **or** a change of more than 200 psi in 10 minutes that cannot be explained by a change in pump rate.
- Critical: above 2,500 psi, **or** annulus pressure rising and falling together with tubing pressure. This "pressure communication" suggests a tubing, packer or casing leak.
- Data quality: single readings above 5,000 psi (the dataset has a spike of 10,313 psi) are treated as sensor spikes unless the next readings confirm them.

Observed values: median ≈ 1,314 psi, 99th percentile ≈ 1,952 psi.

## 7. Injection Flow Rate and Pump Thresholds

Flow BPM is the injection rate in barrels per minute. 1 barrel = 42 US gallons, so GPM = BPM × 42. For example 4.5 BPM ≈ 189 GPM.

- **Design maximum injection rate: 5.0 BPM (≈ 210 GPM).** This is the highest rate recorded in the dataset.
- Normal: 1.0 – 4.9 BPM. Typical steady injection is about 4.3 – 4.5 BPM.
- Warning: 4.9 – 5.0 BPM.
- Critical: above 5.0 BPM.
- Low-flow check: flow below 1.0 BPM while the pump speed is above 200 means the flow meter or the pump needs to be checked.

Pump speed (triplex pump):

- Normal running speed: about 361 – 377 (median 365).
- Warning: 390 – 420.
- Critical: above 420 (the dataset maximum is 423).
- "Calc. Flow from Pump Speed" is the flow estimated from pump strokes. A large difference between this value and the measured Flow BPM may mean pump valve wear or cavitation.

Injected volume: the dashboard calculates injected volume as the sum of Flow BPM readings × (10 / 60) minutes, because data is logged about every 10 seconds. The result is in barrels.

## 8. Pump Suction (Before Triplex) Thresholds — Avoiding Cavitation

CO2 arrives at the triplex pump as a cold liquid. If the suction pressure falls below the CO2 saturation (vapour) pressure at the suction temperature, the CO2 boils inside the pump. This is cavitation. It damages the pump and causes unstable flow.

Rule: Pressure before triplex must stay above the CO2 saturation pressure at the Temperature before triplex, with a margin of at least 20 psi.

Approximate CO2 saturation pressure:

| Suction temperature | Saturation pressure |
|---|---|
| −40 °F (−40 °C) | ≈ 146 psia |
| −20 °F (−29 °C) | ≈ 215 psia |
| −4 °F (−20 °C) | ≈ 286 psia |
| 0 °F (−18 °C) | ≈ 306 psia |
| 20 °F (−7 °C) | ≈ 422 psia |
| 32 °F (0 °C) | ≈ 505 psia |
| 50 °F (10 °C) | ≈ 653 psia |
| 87.98 °F (31.1 °C) | 1,071 psia (critical point) |

Alarm levels:

- Pressure before triplex — Normal: 220 psi or more (typical ≈ 284 psi while injecting). Warning: 200 – 220 psi. Critical: below 200 psi.
- Temperature before triplex — Normal: 10 °F or lower (typical ≈ −7 °F). Warning: 10 – 20 °F. Critical: above 20 °F, because the saturation pressure (≈ 422 psia) is then higher than the normal suction pressure range.

## 9. CO2 Phase Behaviour Reference

- Critical point of CO2: 31.1 °C (87.98 °F) and 7.38 MPa (1,071 psi).
- Above both values CO2 is **supercritical**: dense like a liquid but flows like a gas. This is the preferred state for geological storage because more CO2 fits in the same pore space.
- Supercritical CO2 density at typical storage conditions is about 600 – 800 kg/m³. CO2 gas at surface conditions is about 1.98 kg/m³.
- Storage is usually deeper than about 800 m (≈ 2,600 ft), where normal pressure and temperature keep CO2 supercritical.
- Pressure gradient references: fresh water ≈ 0.433 psi/ft; brine ≈ 0.45 – 0.47 psi/ft; typical fracture gradients ≈ 0.6 – 1.0 psi/ft (site-specific, measured by step-rate or leak-off tests).
- Hydrostatic head on the dashboard (+1,582 psi) is the pressure added by the fluid column between surface and the bottom-hole gauge.

## 10. CO2 Stream Quality Reference

Typical industry targets for a CO2 injection stream (exact values come from the project's own specification):

- CO2 purity: usually 95% or more by volume.
- Water content: kept low (commonly below a few hundred ppm by volume) to prevent corrosion and hydrate formation in pipelines and wells. Free water combined with CO2 forms carbonic acid, which corrodes carbon steel.
- H2S, O2 and other impurities: limited for health, safety and corrosion reasons.

The dashboard dataset does not record CO2 composition, so the chatbot cannot check stream quality from the data.

## 11. Recommended Response Actions

When a value enters the **Warning** level:

1. Confirm the reading is real. Check for gauge moves, sensor spikes or missing data.
2. Stop increasing the injection rate or pump speed.
3. Compare with related sensors. For example check surface pressure and flow rate when CBHP rises.
4. Watch the trend more closely. Use the Prediction page to forecast CBHP and BHT.
5. Use the Injection Optimization Simulator in "Safe Operation" mode to find a flow rate that keeps predicted CBHP below the safe operating limit.

When a value enters the **Critical** level:

1. Reduce the injection rate immediately. If the value does not return below the limit, stop injection (shut-in). Under US EPA Class VI rules, an automatic shut-off system must stop injection when limits are exceeded.
2. Inform the responsible operations engineer and record the event (time, values, actions).
3. For annulus alarms, treat the event as a possible well-integrity (mechanical integrity) problem. Do not restart until integrity is confirmed.
4. Under US EPA Class VI rules, loss of mechanical integrity requires stopping injection, investigating, and notifying the regulator within 24 hours.

## 12. How to Judge Whether a Value Is "Good", "Safe" or "Normal"

1. Identify the parameter (for example CBHP, BHT, surface pressure, annulus pressure, flow rate, pump speed).
2. Check if the well was injecting (Flow BPM > 1.0). Shut-in or no-flow periods have different normal values.
3. Compare the latest value against the Normal / Warning / Critical levels in Section 2.
4. Check the trend: a value still in the Normal level but rising quickly toward the Warning level should be reported.
5. Always say that these are project design-basis thresholds for the FYP digital twin. They are not limits approved by a regulator or operator.

## 13. Glossary

- **CBHP** — Corrected Bottom-Hole Pressure. Bottom-hole gauge pressure corrected for gauge depth and drift.
- **BHP** — Bottom-Hole Pressure. Raw pressure at the bottom-hole gauge.
- **BHT** — Bottom-Hole Temperature.
- **Annulus** — Space between the injection tubing and the casing, sealed by a packer.
- **Triplex pump** — Three-plunger positive-displacement pump that raises CO2 to injection pressure.
- **BPM** — Barrels per minute. 1 barrel = 42 US gallons = 0.159 m³.
- **Fracture pressure** — Pressure at which the rock breaks and opens a fracture. Injection must stay below it.
- **MAIP / MASIP** — Maximum Allowable Injection Pressure / Maximum Allowable Surface Injection Pressure.
- **Mechanical integrity** — The well has no significant leak in the casing, tubing or packer, and no significant fluid movement along the wellbore.
- **Shut-in** — Stopping injection and closing the well.
- **Cavitation** — Vapour bubbles forming and collapsing inside a pump when suction pressure falls below vapour pressure.
- **US EPA Class VI** — US Environmental Protection Agency well class for geologic sequestration of CO2 (40 CFR Part 146, Subpart H).
