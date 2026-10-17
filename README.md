# firmware-calgen

**Generate firmware calibration and configuration constants from engineering specs: traceable to the data sheet, checked by gates, and reviewed before they reach C.**

**[Open the demo site →](https://timotholt.github.io/firmware-calgen/)** It runs entirely in your browser (no install, no server, nothing uploaded).

> **Results are representative and informational only.** Under Texas Instruments' C2000 software license terms, real TI SDK source code is confidential and licensed for internal use only, so no TI code is included, displayed, processed, or emitted here. All C code in this repository is synthetic, written for this demo. Product ratings come from public IntelliPower data sheets; all circuit values, gains, firmware names, and legacy code are invented. Independent demo, not affiliated with or endorsed by AMETEK, IntelliPower, or Texas Instruments. TI, C2000, and Code Composer Studio are trademarks of Texas Instruments.

## Why this exists

This is a working demo for AMETEK IntelliPower's **AI Automation Intern** posting. Read from the posting, the role exists to work on one or more of these problems:

1. **Magnetics design takes too many iterations** (ML on past designs to recommend inductors and transformers).
2. **Firmware changes are hand-edited**: hard-coded values and calibration gains in C source should be generated from engineering specifications.
3. **Specs aren't machine-usable**: requirements must become reliable firmware change rules.
4. **Changes must be provably validated**: test cases, build checks, result review.
5. **Process knowledge isn't written down**: process maps, tool usage, limitations.
6. **Adopt AI responsibly**, and present outcomes to leaders.

**This demo addresses problem 2**, supported by 3, 4, and 5. It does not attempt problem 1; magnetics needs real design data and power-engineering judgment, and a toy would mislead.

**Thesis.** IntelliPower publicly describes a configure-to-order catalog ("2,000+ variations", "building block methodology"), and its engineering postings mention maintaining legacy boards and qualifying alternate components. Each product's ratings and each board's measurement chain end up as constants in firmware. This tool makes that path automatic, traceable, and gated, and uses AI only where the input is messy, measured against a blind answer key and reviewed by a person.

### Assumptions to check in week one

| # | Assumption | Confidence | How I'd check |
|---|---|---|---|
| A1 | Calibration and config constants live in C source (#defines / const tables) | High (the posting says so) | Read one product's source |
| A2 | Many constants derive from data sheet ratings | Medium | Trace ten constants to their origin |
| A3 | Alternate-component substitutions change sense gains | Medium (job postings) | Ask how the last one was handled |
| A4 | The processor is a TI C2000 part | Medium | Look at a board |
| A5 | Specs aren't machine-readable today | Medium (3 of 3 data sheets have an inconsistency) | See the spec source of truth |
| A6 | Some calibration is per unit at a test station | Low | Ask production test |

**What I don't claim:** power-electronics design, loop tuning, magnetics, EMI, certification. Those values come from engineers; the tool carries them safely from spec to source.

## Process

```
data sheet (CSV, cited) ─▶ consistency gate ─▶ + board + chip + design choices
   ─▶ rules → constants ─▶ range · overflow · checks · staleness gates
   ─▶ C header (or patch marked blocks) ─▶ compile + known-answer test ─▶ review report ─▶ sign-off
```

Any gate failure stops the line: nothing is written, and the report says which input caused it.

| Input | Who owns it | Example | Real or invented |
|---|---|---|---|
| `specs/datasheets/*.csv` | product / data sheet | FA10507: 1500 VA, 120 V, "Shutdown at 20% Overload" | **Real**, transcribed verbatim with page citations ([sources](specs/datasheets/SOURCES.md)) |
| `specs/boards/*.yaml` | hardware engineer | 5 mΩ shunt, ×10 amplifier; rev B has an alternate ×20 part | Invented |
| `specs/targets/*.yaml` | processor | F28004x-class float32; F2803x-class IQ20, 10-bit comparator DAC | Public TI data sheet facts; pairing illustrative |
| `specs/variants/*.yaml` | power engineer | 20 kHz switching, loop gains tuned *at* 20 kHz | Invented |
| `specs/rules.yaml` | firmware engineer | `iout_trip = iout_rated * ds.overload_trip_pct` | Textbook relations |

## What it catches (real output)

**An alternate component that silently breaks protection.** Rev B's replacement amplifier doubles the current-sense gain. For the 1500 VA product the trip current no longer fits the sensor:

```
$ calgen check specs/variants/fa10507_revB.yaml
  FAIL  UPS_IOUT_TRIP_DAC_LO       uint16: -585 out of range [0, 65535]
  FAIL  check iout_sense_range      21.2132 <= 15.675 A is false: Peak trip current must sit inside the
                                    current sensor's range, or the sensor saturates before the trip fires
  FAIL  check dac_hi_in_range       4680 <= 4095 is false: Positive trip DAC code must exist on this chip's comparator DAC
3 failure(s); nothing written
```

The same board passes for the 650 VA product.

**Data sheets that disagree with themselves.** All three official data sheets transcribed here contain an internal inconsistency, and the consistency gate finds exactly those: FA10434's input-current and input-frequency rows hold each other's values (the variant carries a written, reviewer-visible override); FA10449's description says "Frequency Changer" while its output row says "Follower"; FA10507 prints two different model numbers.

**Stale engineer-supplied values.** Loop gains record what they were designed against. Change the switching frequency and the PWM period regenerates cleanly, but the gains block generation until an engineer re-tunes or re-approves them.

**Legacy firmware that drifted from the spec.** A read-only audit of a synthetic legacy codebase:

```
$ calgen audit corpus/legacy_ups --variant specs/variants/fa10507.yaml --map corpus/legacy_ups/calgen_map.yaml
  FAIL  ups_config.h:29  VO_NOM         220.0f       spec says 120 (vout_set)
  FAIL  ups_config.h:33  I_TRIP_RMS     14.0f        spec says 15 (iout_trip)
  FAIL  ups_config.h:36  TMR_LD         6000         spec says 5000 (pwm_period)
  ...
16 match, 6 mismatch, 11 unexplained
```

## Every number is traceable

Each generated line carries its formula and inputs, down to the data sheet quote:

```c
/* Comparator DAC code for the positive overcurrent trip
 * = round((target.v_ref / 2 + iout_trip_pk * board.r_shunt * board.g_amp) / target.v_ref * target.dac_max)
 *   target.v_ref = 3.3 V  [target f28004x.yaml]
 *   board.r_shunt = 5 mohm  [board ups_ctrl_revA.yaml]
 *   board.g_amp = 10 ratio  [board ups_ctrl_revA.yaml]
 *   target.dac_max = 4095 counts  [target f28004x.yaml] */
#define UPS_IOUT_TRIP_DAC_HI       3364u          /* 3364 counts, uint16 */
```

Worked by hand (the review report and site typeset this from the same syntax tree the evaluator runs; a test checks they agree):

$$I_\text{rated} = \frac{S}{V_\text{out}} = \frac{1500\ \text{VA}}{120\ \text{V}} = 12.5\ \text{A} \qquad I_\text{trip} = 12.5\ \text{A} \times 1.20 = 15\ \text{A} \qquad I_\text{trip,pk} = \sqrt{2}\cdot 15\ \text{A} = 21.21\ \text{A}$$

$$N_\text{DAC,hi} = \mathrm{round}\!\left(\frac{\tfrac{3.3}{2}\ \text{V} + 21.21\ \text{A}\cdot 5\ \text{m}\Omega \cdot 10}{3.3\ \text{V}}\cdot 4095\right) = \mathrm{round}(3363.68) = 3364$$

## Where AI is used, and where it is not

- The firmware path (spec → constants → gates → C) **never calls a model**.
- AI drafts one thing: what each unexplained legacy constant *is* (category, units, typed vs derived, which rule it corresponds to). One file per call, strict JSON schema, every answer validated, output is a draft for review.
- It's **measured**: a separate agent wrote the synthetic legacy corpus and a blind answer key under clean-room rules; the bar (≥ 90% category, ≥ 85% units) was set before any model ran; the cheapest model that passes is the default.
- Recorded responses are replayed in CI and on the site, so neither needs a key or the network.
- On controlled data (vendor-confidential, CUI, ITAR), point the same interface at an approved internal or local model, or run with `--ai none`. Everything else still works.

| Model | Category | Units | Typed vs derived | Rule mapping | Cost / run |
|---|---|---|---|---|---|
| gpt-5.4-nano | 91% | 97% | 100% | 100% | $0.0043 |
| claude-haiku-5-5, claude-sonnet-5-5 | not recorded yet | | | | |

Honest history: the first recorded run scored 39% on category because of two bugs in my harness (a dropped id suffix; per-file ids colliding in scoring). Both are fixed and tested; the first run is kept in [`corpus/legacy_ups/ai_runs/history/`](corpus/legacy_ups/ai_runs/history/).

## Usage

```bash
uv tool install git+https://github.com/timotholt/firmware-calgen
calgen check specs/variants/fa10507.yaml                    # every constant and gate; writes nothing
calgen build specs/variants/fa10507.yaml --dry-run          # unified diff of the generated header
calgen build specs/variants/fa10507.yaml                    # write firmware/include/calgen_fa10507.h
calgen build specs/variants/fa10507.yaml --patch firmware/src/board.h   # rewrite only CALGEN-marked blocks
calgen report specs/variants/fa10507_revB.yaml              # HTML review report (also for failing builds)
calgen audit corpus/legacy_ups --variant specs/variants/fa10507.yaml --map corpus/legacy_ups/calgen_map.yaml --ai replay:corpus/legacy_ups/ai_runs/openai__gpt-5.4-nano.json
calgen eval corpus/legacy_ups --key corpus/legacy_ups/ANSWER_KEY.yaml --ai replay:corpus/legacy_ups/ai_runs/openai__gpt-5.4-nano.json
calgen vendor && calgen site                                # build the self-contained demo site into out/site
```

Development: `uv run pytest` (144 tests, including generated-file freshness and recorded-AI replay) and `make -C firmware test` (strict C99 build and known-answer tests for every passing variant). In a real adoption, constants change through pull requests: CI runs every gate and attaches the review report.

## Limitations

- **No TI hardware or TI compiler was used.** gcc (CI) and clang (local) stand in for Code Composer Studio; they prove valid C99 under strict warnings, not a C2000 build, and cannot catch C28x issues such as 16-bit `char`.
- Product ratings are public; every circuit value, gain, firmware name, and the legacy code are invented. Formulas are textbook relations, not IntelliPower's design rules.
- Loop gains and compensator coefficients are carried and staleness-tracked, never computed. TI's own tools (powerSUITE) generate such coefficients; this tool's value is linking constants to the product spec, with traceability and gates around tools like that.
- "Shutdown at 20% Overload" is read as a trip at 120% of rated. FA10434's swapped rows are resolved by a written override a reviewer must confirm.
- The AI eval uses a synthetic corpus; it measures the pipeline, not real-world accuracy.
- Per-unit calibration (test-station trims stored in EEPROM or flash) is a separate path, not built here.
- Changing processors: the chip is an independent input, so a port is "swap the target profile, regenerate, diff". The F2803x-class profile regenerates FA10507 in IQ20 fixed point, and an IQ24 overflow of the 265 V limit is caught as an error. Real ports also move pins and peripherals, which this demo does not model.

## Repository map

```
specs/          data sheets (CSV), boards, targets, variants, rules.yaml
src/calgen/     units, expr (restricted evaluator), formats, spec, build, consistency,
                codegen, audit, ai, evals, latex, report, playground, site, vendor, cli
firmware/       tiny fake UPS controller (C99), generated headers, known-answer tests
corpus/         synthetic legacy firmware, blind answer key, reviewed map, recorded AI runs
docs/           PLAN.md, DESIGN_NOTES.md, RESEARCH.md, SUMMARY.md, ADDING_A_CONSTANT.md
```

Built spec-first with Claude Code under my direction: [docs/PLAN.md](docs/PLAN.md) was approved before any code, each milestone landed as its own commit with its tests, and [docs/DESIGN_NOTES.md](docs/DESIGN_NOTES.md) records the reasoning.

MIT license.
