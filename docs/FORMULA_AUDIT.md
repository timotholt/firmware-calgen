# Formula audit (2026-10-17)

Every scientific formula in the app was reviewed by two independent expert-persona model reviews
(magnetics; firmware rules, playground and page claims), then each finding was checked by hand
before fixing. Status: **fixed** unless noted.

## Wrong
| # | Where | Defect | Fix |
|---|---|---|---|
| W1 | `rules.yaml` overload_below_pk_limit | `√2·I_trip < I_pk` covers sinusoidal overloads only; a 3:1 crest-factor load at the 15 A trip peaks at 45 A > 43.75 A, so the claim "normal overloads don't trip the fast protection" was false for the demo's own design load. The crest factor was a hidden Python constant and no check gated it. | Crest factor is a design input (`design.crest_factor`); new check `crest_factor × I_rated < I_pk_limit` (the data sheet's 3:1 at rated load); overload check reworded to say sinusoidal; the playground drawing reads the same input. |
| W2 | `magnetics.py` inductance check | Checked `|err| ≤ A_L tol` and `A_L tol ≤ drawing tol` separately: a +7% offset passed although a −8% core falls below the drawing's lower limit. | Requires the whole A_L spread inside the drawing band: `|err| + tol_AL ≤ tol_drawing`. |
| W3 | `playground.py` output filter | "Half-bridge assumed" for every product, but a 210 V bus gives ±105 V rails, which can't make a 170 V-peak output: FA10434/FA10449 must be full bridges, where the formula is 2× off. | Topology chosen from the bus: half-bridge when V_bus/2 clears the output peak, else unipolar full bridge, L = V_bus/(8·f·ΔI). |

## Misleading
| # | Where | Defect | Fix |
|---|---|---|---|
| M1 | Assumptions page | "Battery on the bus": 36–92 V strings can't sit on a 210/410 V bus. | "Battery coupled to the bus through a bidirectional DC-DC stage (not modelled)"; diagram label. |
| M2 | `rules.yaml`, targets | ADC scale divided by 4095; C2000 ADCs and the F28004x CMPSS DAC use 2ⁿ (4096), a 2.4e-4 error larger than the rule's own 1e-4 tolerance. | Targets carry the TRM divisor (`adc_div` 4096; `dac_div` 4096 on F28004x, 1023 on F2803x, whose 10-bit DAC is specified as V = DACVAL·V_DDA/1023: the reviewer's suggested 1024 there was wrong). |
| M3 | Reports page | Said rev B's "trip current" no longer fits the sensor; it is the hardware peak limit (the RMS trip fits). | Reworded. |
| M4 | `site.py` Assumptions | Toroid fill "40% bare copper"; the check counts wire with enamel. | Reworded. |
| M5 | Output filter requirement | Peak sized at rated current, ignoring the specified 120%/30 s overload (23.9 A vs 20.3 A peak). | Peak sized at the trip level; RMS (heating) at rated. |
| M6 | Sizer | Used nominal A_L while claiming "≥ L at peak"; a −8% core gives 8% less. | Sizer uses minimum A_L (nominal × (1 − tol)) and shows it in the derivation. |

## Nits
| # | Where | Defect | Fix |
|---|---|---|---|
| N1 | Check derivations | 21 of 189 lines printed 3-s.f. inputs that don't reproduce the printed result (e.g., 86.6 vs 86.2 Oe). | l_e, wire area and copper printed to 4 s.f.; test extended to every check line. |
| N2 | Bobbin derivation | "layers × d" was really 1.1 × d_ins. | Label says so. |
| N3 | DC-bias check | Labels hard-coded 80% though `limits.yaml` allows the 50% point. | Labels follow the selected limit. |
| N4 | L-vs-I chart | Derated curve passes below the guaranteed 50% square (single scale set by the 80% point). | Legend says so (conservative by design). |
| N5 | L-vs-I chart | Typical curve drawn past the fit's valid range. | Clipped at the data sheet's 50% point. |
| N6 | Comparator DAC codes | Rounded to nearest, so on F2803x the realised limit (43.79 A) exceeded the design limit. | Rounded toward mid-rail (floor high, ceil low). |
| N7 | Dead-band count | `round` can shorten dead time; clock assumption unstated. | `ceil`; describe states TBCLK = EPWMCLK. |
| N8 | `vout_set` describe | Claimed a per-option header that doesn't exist. | Reworded. |
| N9 | `CALGEN_NUM()` | Truncated while the generator rounds (1 LSB). | Rounds to nearest. |
| N10 | Market presets | Input window scaled by output voltage. | Scaled by `vin_nom` when the sheet has it. |
| N11 | FA10434 sheet | 7.4 A "@90 VAC" is below the transcribed 102 V minimum input. | Override reason notes the inconsistency. |
| N12 | bus_above_output_peak | Passed at modulation index 1.0. | Requires `√2·V_out,hi ≤ m_max·V_bus` with `m_max` = 0.95 (design input). |

## Checked and found correct
All constant formulas and hand values across the five variants; unit engine; float32 and IQ encoding;
typeset derivations vs evaluator; firmware C scaling, overflow and sign handling; rectifier-load
waveform (RMS = I_pk/CF exactly); H = 0.4πNI/l_e (Oe, cm); L = A_L·N² and stacking; the catalog
DC-bias fit, its inverse and derating; cores.csv self-consistency (A_L vs µµ₀A_e/l_e within 4%,
V_e ≈ A_e·l_e within 1%); AWG formula and enamel OD; transformer L_m, ratio and square-wave flux;
bobbin build model; all 12 answer-key verdicts; PFC boost worst case L = V_bus/(4·f·ΔI).

## Second pass (review of the fixes, 2026-10-17)
| # | Severity | Defect | Fix |
|---|---|---|---|
| P1 | Wrong | Output filter peak was the sinusoidal overload (23.9 A) though a rated 3:1 crest-factor load peaks at 37.5 A; sized cores kept only 64–67% of inductance at that peak. | Peak = max(crest factor × rated, √2 × trip) + ripple/2. |
| P2 | Misleading | Half-bridge vs full-bridge choice had no modulation-index margin. | Half-bridge only when m_max × V_bus/2 clears the output peak. |
| P3 | Nit | README realised limit 43.747 A (it is 43.7476). | 43.748 A. |
| P4 | Nit | `CALGEN_NUM` ties away from zero; the generator ties to even. | Documented in the macro comment. |
| P5 | Nit | `ceil`/`floor` on binary floats can step one count on decimal-exact products. | Noted in the rule; shipped values pinned by tests. |
| P6 | Nit | Sizer table "L at 0 A" showed the minimum-A_L value unlabelled. | Header says min A_L. |

The F2803x comparator DAC divisor (1023) was re-checked against TI's current reference manual, SPRUI10A (DAC Reference: V = DACVAL × (VDDA − VSSA) / 1023), as well as SPRUGE5F §2.3.1.

## Presentation pass (2026-10-17)
Two further reviews read every page as a hiring engineer would (numbers, units, labels, legends, captions, claims). About 80 items were fixed; the ones that touched correctness:
- The audit now judges a legacy scale factor against the rule's own quantization tolerance, so `K_VS = VBUS_FS / 4095` is reported (0.02% off the 4096 divisor) instead of passing at 0.5%.
- Flagged magnetics records state what failed ("stated inductance doesn't match Aₗ × N² within tolerance"), not the passing check's title.
- Transformers show AC winding loss as not modelled, with the skin depth at the drive frequency.
- The unedited playground download is byte-identical to the committed header (tested).
- Checks typeset their inputs (h, m_max, CF) the way constants do; scale factors print in V/count; cell counts print as cells; µs typesets correctly.
The constant description for `vout_set` no longer claims a per-option header; because constant descriptions are part of the AI-audit prompt, the three gpt-5.4-nano runs were re-recorded (about $0.013 in total, approved): category 83% (was 85%), units 95%, rule mapping 99%. Category stays below the 90% bar. The previous runs are kept in `corpus/legacy_ups/ai_runs/history/`.
