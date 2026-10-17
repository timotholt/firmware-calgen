# Design notes: how I approached this

## 1. Start from the posting, not the tool

The posting names two initiatives. The second, automating firmware modification and calibration from engineering specifications, is the closest match to my background (BIOS and driver firmware in C and x86 assembly, hardware bring-up), so the demo targets it and says plainly that it does not attempt the magnetics initiative.

I wrote the posting's asks as six problems (see the README) and a thesis, then ranked user stories by how directly the posting supports them. Every feature in the repository traces to one of those stories; features that didn't (a dashboard, a chat interface) were left out.

## 2. Public research before design

- The company publicly describes a configure-to-order catalog ("2,000+ variations", "building block methodology"); model strings encode every option.
- Its engineering job postings mention maintaining legacy products, combining legacy boards with new systems, and qualifying alternate components.
- I transcribed three official data sheets by hand. Each turned out to contain an internal inconsistency. That made "check the spec before trusting it" a first-class gate rather than an afterthought.

Details and citations: [RESEARCH.md](RESEARCH.md).

## 3. Hypotheses I changed my mind about

- **"Chip obsolescence is the driver."** Attractive, but the posting never mentions it and the current TI parts I checked are all active. Demoted to an extension: the chip is still an independent input, so a port is "swap the profile, regenerate, diff".
- **"Fixed-point conversion is the hard part."** Modern C2000-class parts have an FPU and keep physical constants as floats. Fixed point still matters for register values (DAC codes, PWM counts) and legacy targets, so it stays, but traceability, conformance, and staleness became the center.
- **"Calibration means per-design constants."** It may also mean per-unit trims at a test station. The demo builds the per-design path and names the per-unit path as separate.

## 4. Design decisions

| Decision | Why |
|---|---|
| Specs as plain CSV/YAML, rules in YAML | Engineers edit data, not Python; reviewable diffs |
| Restricted AST evaluator, never `eval` | Formulas come from files; safety and auditability |
| Units on every value | Adding volts to amps should be an error, not a number |
| Overflow is an error, never saturation | Silent saturation in a trip threshold is a safety bug |
| Fail closed | A partially written header is worse than none |
| Deterministic, timestamp-free output | Diffs show only real changes; generated files are checked in CI |
| Product, board, chip, and design as separate inputs | Each axis of change (variant, alternate part, processor, tuning) is one edit |
| Staleness tracking for engineer-supplied values | The tool can't tune a loop, but it can notice when the basis of a tuning changed |
| LaTeX generated from the evaluated syntax tree | The math shown is provably the math run |
| AI only for drafting legacy-constant classifications | Deterministic where correctness matters; measured where judgment helps |
| Provider-neutral AI backends with recorded replay | Runs offline in CI and on the site; swap for an approved internal model |
| Static site with Python in the browser | Self-contained, free to host, nothing uploaded |

## 5. Licensing and clean-room boundaries

I downloaded TI's DigitalPower SDK under my own account to understand how real C2000 power firmware is laid out. Its reference firmware is licensed as confidential, internal-use material, so none of it, nor anything derived from it, appears in this repository or on the site. The legacy corpus was written by a separate agent from public knowledge only, under explicit rules (no vendor identifiers, own naming and values, a synthetic-example header on every file).

## 6. What I'd verify first with your engineers

1. Where the hard-coded gains live, and which axis (variant, board revision, or processor) causes the most edits.
2. How the last alternate-component substitution was handled in firmware.
3. The source of truth for a variant's spec today.
4. Which TI parts and toolchain versions are in use.
5. Whether calibration includes per-unit trims at a test station.
6. What "build checks" and "test cases" consist of today.

## 7. How it was built

Spec-first with Claude Code under my direction: the plan in [PLAN.md](PLAN.md) was approved before code, then built in milestones, each a commit with its own tests. Two bugs the tests caught are worth recording: an include-order bug that made a fixed-point trip read as 15.7 million amps (caught by the known-answer C test), and an AI-harness bug that made a good model look bad (caught by reading the recorded responses before trusting the score).
