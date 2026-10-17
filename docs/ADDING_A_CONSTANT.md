# Adding a constant

Constants are data. Adding one means editing `specs/rules.yaml`, not Python.

1. **Write the rule.**

   ```yaml
   - id: iout_alarm
     symbol: UPS_IOUT_ALARM_A          # C name in the generated header
     describe: Overload alarm current (RMS)
     formula: iout_rated * ds.overload_alarm_pct
     unit: A                           # the constant's own unit; formulas are unit-checked
     format: target                    # or float32, uint16, iq20, q0.15, ...
     block: out                        # which power-flow block it belongs to
     latex: 'I_{\text{alarm}}'         # symbol for typeset derivations
     optional: true                    # skip (and say so) when a data sheet lacks the input
     min: 0.1                          # optional range limits, in `unit`
     max: 100
   ```

   Names in formulas: `ds.*` (data sheet field), `board.*`, `target.*`, `design.*`, or the `id` of any constant defined earlier in the file. Allowed: numbers, `+ - * /`, integer powers, `sqrt`, `min`, `max`, `round`, `ceil`, `floor`, `abs`.

2. **If it needs a new input**, add it where it is owned: a data sheet column (with its source), a board or target `params` entry (value + unit + note), or a variant `design` entry. Engineer-tuned values should declare `designed_against` so the staleness gate can watch their basis.

3. **If it has a relationship to enforce**, add a check:

   ```yaml
   - id: alarm_below_trip
     describe: Overload alarm must come before the trip
     lhs: iout_alarm
     op: "<"
     rhs: iout_trip
     block: out
   ```

4. **Give the input a LaTeX symbol** under `symbols:` if it's new.

5. **Regenerate and review.**

   ```bash
   calgen check specs/variants/fa10507.yaml
   calgen build specs/variants/fa10507.yaml --dry-run
   calgen report specs/variants/fa10507.yaml
   ```

6. **Add a known answer.** Work the value out by hand and add it to `tests/test_build.py` and, if firmware uses it, to `firmware/test/test_known_answer.c`.

7. **Regenerate committed headers** for every variant; CI fails if a committed generated file is stale.
