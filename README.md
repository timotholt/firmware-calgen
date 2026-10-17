# firmware-calgen

**From data sheet to firmware C code: calibration and configuration constants generated from engineering specs, with every constant traced to its source and checked before it goes into the code.**

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
| `specs/boards/*.yaml` | hardware engineer | 2 mΩ shunt, ×10 amplifier; rev B has an alternate ×20 part | Invented |
| `specs/targets/*.yaml` | processor | F28004x-class float32; F2803x-class IQ20, 10-bit comparator DAC | Public TI data sheet facts; pairing illustrative |
| `specs/variants/*.yaml` | power engineer | 20 kHz switching, loop gains tuned *at* 20 kHz | Invented |
| `specs/rules.yaml` | firmware engineer | `iout_trip = iout_rated * ds.overload_trip_pct` | Textbook relations |

## What it catches (real output)

**An alternate component that silently breaks protection.** Current protection has two layers, as in real inverters: a *timed RMS overload* in software (the data sheet's "Shutdown at 20% Overload", acting after a delay) and a *hardware peak-current limit* on the comparator for short circuits, set at 3.5 × rated RMS so 3:1 crest-factor loads such as computer power supplies don't trip it. Rev B's replacement amplifier doubles the current-sense gain, and for the 1500 VA product the hardware limit no longer fits the sensor:

```
$ calgen check specs/variants/fa10507_revB.yaml
  FAIL  UPS_IOUT_PKLIM_DAC_LO      uint16: -124 out of range [0, 65535]
  FAIL  check iout_sense_range      43.75 <= 39.1875 A is false: Hardware peak limit must sit inside the
                                    current sensor's range, or the sensor saturates before the limit fires
  FAIL  check dac_hi_in_range       4219 <= 4095 is false: Positive peak-limit DAC code must exist on this chip's comparator DAC
3 failure(s); nothing written
```

The same board passes for the 650 VA product.

**Data sheets that disagree with themselves.** All three official data sheets transcribed here contain an internal inconsistency, and the consistency gate finds exactly those: FA10434's input-current and input-frequency rows hold each other's values (the variant carries a written, reviewer-visible override); FA10449's description says "Frequency Changer" while its output row says "Follower"; FA10507 prints two different model numbers.

**Stale engineer-supplied values.** Loop gains record what they were designed against. Change the switching frequency and the PWM period regenerates cleanly, but the gains block generation until an engineer re-tunes or re-approves them.

**Legacy firmware that drifted from the spec.** A read-only audit of a synthetic legacy codebase separates values that contradict the data sheet from values that only differ from this demo's (invented) design choices:

```
$ calgen audit corpus/legacy_ups --variant specs/variants/fa10507.yaml --map corpus/legacy_ups/calgen_map.yaml
  FAIL  ups_config.h:29  VO_NOM         220.0f       contradicts data sheet: 120 (vout_set)
  FAIL  ups_config.h:33  I_TRIP_RMS     14.0f        contradicts data sheet: 15 (iout_trip)
  diff  ups_config.h:26  VBUS_REF       400.0f       differs from design value: 410 (vbus_set)
  diff  protect.c:34     <inline>       21.2f        differs from design value: 43.75 (iout_pk_limit)
  ...
11 match, 3 contradict the data sheet, 9 differ from design values, 10 unexplained
```

The `protect.c:34` line is the interesting one: the legacy fast trip sits at the *peak of the RMS overload level*, so a fully loaded unit feeding crest-factor loads would trip.

## Every number is traceable

Each generated line carries its formula and inputs, down to the data sheet quote:

```c
/* Comparator DAC code for the positive hardware peak-current limit
 * = round((target.v_ref / 2 + iout_pk_limit * board.r_shunt * board.g_amp) / target.v_ref * target.dac_max)
 *   target.v_ref = 3.3 V  [target f28004x.yaml]
 *   board.r_shunt = 2 mohm  [board ups_ctrl_revA.yaml]
 *   board.g_amp = 10 ratio  [board ups_ctrl_revA.yaml]
 *   target.dac_max = 4095 counts  [target f28004x.yaml] */
#define UPS_IOUT_PKLIM_DAC_HI      3133u          /* 3133 counts, uint16 */
```

Worked by hand (the review report and site typeset this from the same syntax tree the evaluator runs; a test checks they agree):

$$I_\text{rated} = \frac{S}{V_\text{out}} = \frac{1500\ \text{VA}}{120\ \text{V}} = 12.5\ \text{A} \qquad I_\text{OL} = 12.5\ \text{A} \times 1.20 = 15\ \text{A RMS (timed)} \qquad I_\text{pk,lim} = 3.5 \times 12.5\ \text{A} = 43.75\ \text{A}$$

$$N_\text{DAC,hi} = \mathrm{round}\!\left(\frac{\tfrac{3.3}{2}\ \text{V} + 43.75\ \text{A}\cdot 2\ \text{m}\Omega \cdot 10}{3.3\ \text{V}}\cdot 4095\right) = \mathrm{round}(3133.30) = 3133$$

## Where AI is used, and where it is not

- The firmware path (spec → constants → gates → C) **never calls a model**.
- Why not a spreadsheet? About a third of the constants restate the data sheet; the value is not the arithmetic but the gates (consistency, range, overflow, staleness, fail-closed), the per-line provenance, and running it in CI across a catalog of variants.
- AI drafts one thing: what each unexplained legacy constant *is* (category, units, typed vs derived, which rule it corresponds to). One file per call, strict JSON schema, every answer validated, output is a draft for review.
- It's **measured, on a small set**: 33 constants in 3 synthetic legacy files, one model so far. A separate AI session wrote the corpus and its answer key under clean-room rules; the classifier never sees the key. The bar (≥ 90% category, ≥ 85% units) was set before any model ran, and no model has passed it yet, so the AI step is a review aid, not a default.
- Recorded responses are replayed in CI and on the site, so neither needs a key or the network.
- On controlled data (vendor-confidential, CUI, ITAR), point the same interface at an approved internal or local model, or run with `--ai none`. Everything else still works.

| Model | Runs | Category (mean, range) | Units | Typed vs derived | Rule mapping | Cost / run | Verdict |
|---|---|---|---|---|---|---|---|
| gpt-5.4-nano | 3 | 85% (82–88) | 94% | 100% | 96% | $0.0047 | below the category bar |

gpt-5.4-nano, the low-cost model tried, maps legacy constants to the right rule almost every time, which is what the audit needs, but its category labels disagree with the key on borderline cases often enough to miss the bar I set in advance. I report that rather than move the bar; the next step would be a stronger model. The corpus is also friendlier than real legacy firmware (most constants have comments), which flatters these numbers.

History: an earlier single run scored 91% on category with a different rule set, and the very first run scored 39% because of two bugs in my harness (a dropped id suffix; per-file ids colliding in scoring), both fixed and tested. Every run is kept in [`corpus/legacy_ups/ai_runs/`](corpus/legacy_ups/ai_runs/).

## Usage

```bash
uv tool install git+https://github.com/timotholt/firmware-calgen
calgen check specs/variants/fa10507.yaml                    # every constant and gate; writes nothing
calgen build specs/variants/fa10507.yaml --dry-run          # unified diff of the generated header
calgen build specs/variants/fa10507.yaml                    # write firmware/include/calgen_fa10507.h
calgen build specs/variants/fa10507.yaml --patch firmware/src/board.h   # rewrite only CALGEN-marked blocks
calgen report specs/variants/fa10507_revB.yaml              # HTML review report (also for failing builds)
calgen audit corpus/legacy_ups --variant specs/variants/fa10507.yaml --map corpus/legacy_ups/calgen_map.yaml --ai replay:corpus/legacy_ups/ai_runs/openai__gpt-5.4-nano__run1.json
calgen eval corpus/legacy_ups --key corpus/legacy_ups/ANSWER_KEY.yaml --ai replay:corpus/legacy_ups/ai_runs/openai__gpt-5.4-nano__run1.json
calgen vendor && calgen site                                # build the self-contained demo site into out/site
```

Development: `uv run pytest` (tests include generated-file freshness and recorded-AI replay) and `make -C firmware test` (strict C99 build and known-answer tests for every passing variant). In a real adoption, constants change through pull requests: CI runs every gate and attaches the review report.

## Limitations

- **No TI hardware or TI compiler was used.** gcc (CI) and clang (local) stand in for Code Composer Studio; they prove valid C99 under strict warnings, not a C2000 build, and cannot catch C28x issues such as 16-bit `char`.
- Sensing is simplified: dividers and the current shunt are drawn referenced to the controller. On an isolated unit (FA10507) a real design senses on the primary side or through isolation amplifiers or current transformers; the scale-factor math is the same.
- One rule set assumes a boost-PFC, DC-bus, inverter topology. A real catalog spans topologies and would need rule sets per platform.
- Direction of truth: at a real company, firmware limits probably live in a design or change database and the data sheet is written from it. The tool would read whichever is the source of truth; public data sheets are used here because they're what's public.
- PWM uses up-down (center-aligned) counting; dead-time limits come from each chip profile. EPWM clock = SYSCLK is assumed per target and flagged.
- Product ratings are public; every circuit value, gain, firmware name, and the legacy code are invented. Formulas are textbook relations, not IntelliPower's design rules.
- Loop gains and compensator coefficients are carried and staleness-tracked, never computed. TI's own tools (powerSUITE) generate such coefficients; this tool's value is linking constants to the product spec, with traceability and gates around tools like that.
- "Shutdown at 20% Overload" is read as a timed RMS trip at 120% of rated; the 30 s delay and the 3.5× hardware peak-limit factor are invented design values. FA10434's swapped rows are resolved by a written override a reviewer must confirm.
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

**License:** © 2026 Timothy Otholt. All rights reserved. You may view the source and run the demo to evaluate my work; no other use, including copying, reuse in job applications, or AI training. See [LICENSE](LICENSE) and [third-party notices](THIRD_PARTY_NOTICES.md).
