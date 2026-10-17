# legacy_ups corpus (SYNTHETIC)

Everything here is invented for the calgen demo: no real product, no vendor SDK code, written from general engineering knowledge. The eval scores the calgen audit pipeline against a key we wrote ourselves. It does not measure accuracy on real-world firmware.

**Scenario.** A small company's 2009-era firmware for a 1500 VA, 120 V / 60 Hz double-conversion UPS (FA10507 class). It was carried over from a 1250 VA export board and patched by hand for the 120 V build and later a LiFePO4 battery option. The files are `ups_config.h` (limits, setpoints, PWM, gains, battery, IO), `sense_scale.h` (ADC and comparator scaling) and `protect.c` (protection logic with inline magic numbers and `static const` values).

**Seeded issues**, compared with `firmware/include/calgen_fa10507.h`:
- `VO_NOM` is 220 V; it should be 120. `VO_HI` is derived from it, so it is also wrong (226.6 instead of 123.6).
- `I_TRIP_RMS` is 14.0 A; it should be 15.0. It is duplicated as `k_trip_a = 15.0f` in protect.c, and that copy is correct.
- `TMR_LD` is 6000. Its comment says 25 kHz, which is stale: that only holds for a 150 MHz clock. At 100 MHz, 6000 counts is 16.67 kHz. It should be 5000.
- `VBAT_CUT` is 78.4 V, which comes from the lead-acid 1.75/2.00 V-per-cell ratio. It should be 69.888 V, from the LiFePO4 ratio of 0.78.
- `VBUS_REF` is 400 V; it should be 410.
- `DB_CNT` has the wrong unit in its comment ("300 us" should be 300 ns). Its value is correct.
- Cryptic names: `K_VS`, `TMR_LD`, `DB_CNT`.
- Trap: `ol_hold_ms = 5000` (a time in ms) has the same number as the correct PWM period but is unrelated.

**How the key was built.** `ANSWER_KEY.yaml` has one entry for every numeric `#define`, every `static const` and every inline literal in code: 33 entries (16 match, 6 mismatch, 11 not_applicable). Each `correct_value` comes from calgen_fa10507.h. A value counts as a match when it is within 0.5% of that value (within 1 count for integers). Line numbers, literals and conformance were checked by a script against the final files.

**Not keyed:**
- The trivial literals `0.0f` (protect.c line 32), `1.0f` (inside `VO_HI`), `1` (the enum start `FLT_OC = 1` and `FLT_LOG_LEN - 1`) and the `++`/`--` counters.
- Numbers inside comments, such as revision dates, divider values and "1.75 V/cell".
- The include guards.
