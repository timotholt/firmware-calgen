# legacy_ups corpus (SYNTHETIC)

Everything here is invented for the calgen demo: no real product, no vendor SDK code, written from general engineering knowledge. The eval scores the calgen audit pipeline against a key we wrote ourselves. It does not measure accuracy on real-world firmware.

**Scenario.** A small company's 2009-era firmware for a 1500 VA, 120 V / 60 Hz double-conversion UPS (FA10507 class). It was carried over from a 1250 VA export board and patched by hand for the 120 V build and later a LiFePO4 battery option. The files are `ups_config.h` (limits, setpoints, PWM, gains, battery, IO), `sense_scale.h` (ADC and comparator scaling) and `protect.c` (protection logic with inline magic numbers and `static const` values).

**Seeded issues**, compared with `firmware/include/calgen_fa10507.h` (FA10507, board rev A, F28004x-class):
- `VO_NOM` is 220 V; it should be 120. `VO_HI` is derived from it, so it is also wrong (226.6 instead of 123.6).
- `I_TRIP_RMS` is 14 A; it should be 15. It is duplicated as `k_trip_a = 15.0f` in protect.c, and that copy is correct.
- `TMR_LD` is 6000. Its comment says 25 kHz, which only holds in up-count mode at 150 MHz. In up-down mode at 100 MHz, 6000 counts is 8.33 kHz. For 20 kHz it should be 2500.
- `DB_CNT` is 30 counts, 300 ns at 100 MHz; the design dead time is 1 µs, so it should be 100. Its comment also has the wrong unit ("300 us").
- `VBAT_CUT` is 78.4 V, the lead-acid 1.75/2.00 V-per-cell ratio applied to 89.6 V. The LiFePO4 cutoff is 28 cells × 2.5 V = 70 V.
- `VBUS_REF` is 400 V; it should be 410.
- The fast overcurrent trip sits at 21.2 A, the peak of the 15 A RMS overload (inline in `prot_fast`, and as `CMP_DAC_HI` = 3364 on the legacy 33 A scale). A fully loaded unit feeding 3:1 crest-factor loads would trip it. The hardware peak limit should be 43.75 A (codes 3134 and 962).
- `IO_FS_PK` is 33 A because the legacy board used a 5 mΩ shunt; rev A uses 2 mΩ, so 82.5 A.
- `ol_hold_ms` is 5 s; the design overload delay is 30 s.
- `K_VS` divides by `ADC_FULL` = 4095, the maximum code; on C2000 ADCs one count is V_ref/4096, so it should be 0.121655 (0.02% off: small, but outside the rule's 1e-4 tolerance, and the classic off-by-one-LSB).
- Cryptic names: `K_VS`, `TMR_LD`, `DB_CNT`.

The audit separates these: 3 contradict the data sheet (`VO_NOM`, `VO_HI`, `I_TRIP_RMS`); the other 10 mismatches only differ from design values, which is a conversation with an engineer, not necessarily a bug.

**How the key was built.** `ANSWER_KEY.yaml` has one entry for every numeric `#define`, every `static const` and every inline literal in code: 33 entries (10 match, 13 mismatch, 10 not_applicable). Each `correct_value` comes from calgen_fa10507.h. A value counts as a match when it is within 0.5% of that value, or within the rule's own quantization tolerance when it has one (within 1 count for integers). Line numbers, literals and conformance were checked by a script against the final files.

**Not keyed:**
- The trivial literals `0.0f` (protect.c line 32), `1.0f` (inside `VO_HI`), `1` (the enum start `FLT_OC = 1` and `FLT_LOG_LEN - 1`) and the `++`/`--` counters.
- Numbers inside comments, such as revision dates, divider values and "1.75 V/cell".
- The include guards.
