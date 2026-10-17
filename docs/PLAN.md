# firmware-calgen — Plan

Status: approved 2026-10-16; v1 built M0–M9 on 2026-10-16. Deviations from this plan, as built:
- Site is static on GitHub Pages with the engine running in the browser (Pyodide); no hosted server, no live AI on the site (decided with Tim). KaTeX renders client-side from a local copy; pages fall back to readable LaTeX text without JavaScript.
- KaTeX 0.16.22, Pyodide 0.27.7, and PyYAML's Pyodide wheel are pinned and checksum-verified by `calgen vendor`; nothing loads from a CDN at runtime.
- AI comparison: gpt-5.4-nano recorded over 3 runs: 85% mean category (below the 90% bar), 94% units, 96% rule mapping (re-recorded after the input-frequency rules were added); reported as below the bar, bar not moved. Claude Haiku 5.5 / Sonnet 5.5 not recorded (no Anthropic key available).
- After an expert review (2026-10-16): current protection split into a timed RMS overload and a hardware peak limit; sensor resized; PWM up-down; per-chip dead-band limits; battery cutoff from cell count; audit verdicts split into "contradicts data sheet" and "differs from design value".
- Calibration add-on (S6) not built; listed as a limitation.
- The AI audit corpus is the clean-room synthetic corpus only; TI SDK firmware is not used for any published result (license).
Repo: `github.com/timotholt/firmware-calgen` (private until Tim approves going public). CLI name: `calgen`.
Yardstick: `~/Projects/jobhunter/applications/ametek-ai-intern/THESIS.md` (problems 1a–1f, user stories S1–S9, assumptions A1–A7, principles 1–10). Every feature names the story it serves.

## 0. What changed from v1 (and why)

| Change | Reason |
|---|---|
| Center of gravity: **traceability + conformance + staleness**, not fixed-point math | TI's real C2000 reference firmware keeps ~15–25 hand-typed physical constants as floats per settings header; fixed-point matters mainly for register counts and legacy chips |
| New core gate: **spec-vs-firmware conformance audit** (deterministic) | The realistic week-one tool: read existing firmware, compare to the data sheet, flag mismatches. No trust in generation required |
| New gate: **staleness** | Engineer-supplied values (compensator coefficients, PI gains) are designed against specific inputs (e.g., 20 kHz switching). If those inputs change, the values are silently wrong |
| AI audit corpus = **clean-room synthetic legacy C** | TI SDK firmware is "TI Commercial" — confidential, internal-use only (license §2a, §2g, §6). It is never hosted, displayed, processed by cloud tools, or used to derive published results |
| Reviewer needs **only a browser** | Can't assume any installed tools |
| **Static site on GitHub Pages; engine runs in the browser (Pyodide)** — no server | Free, permanent, no accounts; nothing a visitor types leaves their browser (fits the defense-data pitch); same Python engine as CLI/tests. Mandatory license notice at top of page 1 |
| Credit TI powerSUITE | TI already generates compensator coefficients via a GUI; calgen's value is spec linkage, traceability, and gates around such tools — not "nobody generates constants" |

## 1. One-sentence scope

**A data sheet + a board definition + a target chip go in; traceable, gated, reviewed C constants come out — and existing firmware can be audited against the spec.**

Focus: problem **1b**, supported by 1c (spec format + data sheet consistency), 1d (gates + review report), 1e (process map, limits). Problem 1a (magnetics) out of scope.

## 2. What ships

### 2.1 Inputs (plain files an engineer edits)

| File | Content | Real or invented | Story |
|---|---|---|---|
| `specs/datasheets/fa10449.csv`, `fa10434.csv`, `fa10507.csv` | Transcription of the official IntelliPower data sheet fields, each row with source URL + page | **Real public numbers**, cited; PDFs not committed | S1, S4 |
| `specs/boards/ups_ctrl_revA.yaml`, `revB.yaml` | Sense chain: dividers, shunt + amplifier gain, ADC reference/bits. Rev B swaps the current-sense amplifier (alternate component) | **Invented**, labeled | S5 |
| `specs/targets/f28004x.yaml` (primary, float32), `f2803x.yaml` (legacy, IQ24) | Clocks, ADC bits/ref, comparator DAC bits, number format | TI public datasheet facts; pairing with IntelliPower **illustrative** | S9 fixture, principle 7 |
| `specs/rules.yaml` | Per constant: C symbol, formula, units, format, min/max, tolerance, source fields, `designed_against` (for staleness) | Textbook relations; engineer-editable | S1, S2 |
| `specs/variants/*.yaml` | Selects data sheet + board rev + target + engineer-supplied inputs (PI gains, margins) | Gains invented, labeled | S1 |

Loop gains/coefficients are **inputs only** — validated, converted, staleness-tracked, never computed.

### 2.2 Constants (~15–20)

Rated output current; overload alarm/trip currents and action; Vout setpoint and regulation band; input voltage and frequency windows; output frequency + changer/follower mode; battery string nominal and low-battery cutoff; sense full-scale values (board × target) for Vbus/Vout/Iout/Vbatt; comparator trip DAC code (A → sense V → counts); PWM period and deadband counts (clock-derived); PI gains (carried).

### 2.3 Engine

- Restricted AST formula evaluator (no `eval`); unit/dimension tracking over V, A, s.
- Number formats: **float32 primary**; unsigned/signed integer register counts and IQn/Qm.n on the legacy target — explicit rounding, overflow = failure, quantization error vs tolerance.
- **Final artifact is C:** generated `include/calgen_<variant>.h` (default; `#define`s grouped by power-flow block, engineer-supplied values fenced off with `designed_against`, synthetic-demo notice in the banner, no timestamp), or patch between `/* CALGEN:BEGIN name */ … /* CALGEN:END name */` leaving all else byte-identical. Provenance comment on every line; DO-NOT-EDIT banner with spec hash and tool version. Deterministic, byte-identical.
- **Typed vs derived:** report states which constants are derived from inputs and which are engineer-typed.

### 2.4 Gates (fail closed)

| Gate | Checks | Story |
|---|---|---|
| Schema | Fields, types, enums, units | S3 |
| Data sheet consistency | Model-string tokens vs fields; changer/follower contradictions; value-vs-label sanity; W ≤ VA; battery string ≈ cells × per-cell nominal. Expected to flag the real FA10449/FA10434/FA10507 issues | S4 |
| **Conformance audit** | Scan existing C (`#define`/const), map to spec fields via rules, report matches / mismatches / unmapped magic numbers (e.g., "data sheet 120 V / 60 Hz; firmware nominal 220 V") | S1, S4, new |
| **Staleness** | Each engineer-supplied constant records the inputs it was designed against; flag when they change (e.g., switching frequency changed → compensator coefficients stale) | S3, new |
| Range / overflow / quantization | Within rule limits, representable, error within tolerance | S3 |
| Diff | Unified diff vs current | S2 |
| Build | Sample firmware compiles: C99, `-Wall -Wextra -Werror`, gcc in CI (Apple clang locally) — **stand-in for TI Code Composer Studio / cl2000, stated plainly** | S3 |
| Known-answer | Compiled C test asserts generated constants equal hand-worked values | S3, principle 8 |

### 2.5 Sample firmware (`firmware/`) — ours, compiles

Tiny fake UPS controller in C99: `board.h` (marker blocks), `ups_ctrl.c` (uses constants in trip check, ADC scaling, PWM setup — no real control loop), `test_known_answer.c`, `Makefile`. Fixed-width types; note on C28x 16-bit `char`/`int` a host compiler can't catch.

### 2.6 Synthetic legacy corpus (`corpus/legacy_ups/`) — ours, audit target

Clean-room rules:
1. Sources: public TI datasheets/app notes/design guides and textbook relations only — nothing from the TI SDK.
2. Own naming scheme (e.g., `UPS_VBUS_FS_V`), own values derived from our invented board, own layout and style ("small company's 2009 firmware": magic numbers, stale comments, a duplicated constant, one wrong unit comment).
3. Header on every file:
   ```c
   /* SYNTHETIC EXAMPLE — written for the calgen demo. Not from any real product
    * or vendor SDK. Names and values are invented to resemble typical
    * power-converter firmware. May not compile on any target. */
   ```
4. Written by a separate agent that also writes the answer key; the classifier never sees the key (blind).

### 2.7 AI step — legacy audit classification (optional, measured)

1. Deterministic scan (conformance gate) produces candidates.
2. LLM classifies each: category (sense full-scale, trip limit, clock, PWM timing, control gain, compensator coefficient, pin/peripheral map, other), units, typed-vs-derived, proposed spec field/rule. Structured output against a JSON schema; pinned model, configurable.
3. Output is a draft `audit.yaml` + report section for human review; nothing applied automatically; AI never writes firmware.
4. Evals vs the blind answer key: per-field accuracy, confusion table, cost/latency. README states: "synthetic corpus; measures the pipeline, not real-world accuracy."

Backends (provider-neutral plug-in interface, one small module each): `replay` (default; recorded responses committed, so CI and the demo need no key), `openai` (`OPENAI_API_KEY`), `anthropic` (`ANTHROPIC_API_KEY`), `none`. Every model answer is validated against the JSON schema; invalid answers count as eval failures, never silently accepted. Keys live only in a local, gitignored `.env`.

**Model comparison eval:** run the same blind eval on 2–3 models (candidates: an OpenAI nano-tier model, Claude Haiku 5.5, Claude Sonnet 5.5 — exact model IDs and current prices pinned and checked at build time). Publish accuracy per field, schema-failure rate, cost per run, latency. **Default model = cheapest one that passes the accuracy bar** (bar set before running, e.g. ≥ 90% category, ≥ 85% units). README notes cost at company scale (thousands of files), where the tiers actually differ.

Deployment note: on controlled data (CUI/ITAR/vendor-confidential), use a local model behind the same interface or disable; the firmware path never depends on the AI step.

Optional upgrade (not v1): an openly licensed real corpus (e.g., LibreSolar charge-controller firmware, Apache-2.0) — research first.

### 2.8 Calibration add-on (S6)

`calgen cal`: two measured points → gain + offset → checks → small generated header/JSON. Labeled as the per-unit path.

### 2.9 CLI (for engineers / CI)

`calgen check | build [--dry-run] [--patch] | audit <src> | report | cal | eval`. Plain colored text, same vocabulary as the report. Install: `uv tool install git+https://github.com/timotholt/firmware-calgen`. PR-workflow example: GitHub Action runs all gates on spec changes and attaches the review report.

## 3. Reviewer interface — browser only

### 3.1 Demo site — GitHub Pages, runs in the browser

URL: `https://timotholt.github.io/firmware-calgen/`. Fully static; built by a GitHub Action from the repo. The live playground runs calgen's own Python package in the visitor's browser via **Pyodide** (pinned version from a CDN), so the math, gates, LaTeX, and generated C come from the same code the CLI and tests use. Each page ships **pre-rendered for the default product (FA10507)** so it displays instantly; inputs become live once Python loads (a few seconds, "engine loading…" indicator). Serves only our code, our synthetic corpus, and public data sheet facts.

Pages:
1. **Home** — license notice (3.2), then problem statement (posting 1a–1f → focus 1b), assumptions table, what I don't know.
2. **Review reports** — 3 variants × board rev A/B × target; engineering-document look, gate pills, provenance, diff, sign-off block.
3. **Playground** — three stacked layers:
   - **Top: product list (left, inverted selection) + power-flow diagram (right)** of a generic online double-conversion UPS: AC in → rectifier/PFC → DC bus → inverter → AC out, battery attached to the DC bus. Each block shows its numbers, tagged **data sheet** (cited) / **derived** (textbook relation, e.g. V_bus,min ≥ √2·V_in,max; V_bus > √2·V_out) / **design choice** (invented, labeled, e.g. bus setpoint margin). Clicking a block filters the constants list below to that block. No animation, no efficiency/loss numbers (not modeled).
   - **Middle:** inputs grouped by owner (below).
   - **Bottom:** constants list + typeset derivation (§3.1a), and tabs **Derivation | Generated C | Diff**. Generated C tab shows the header with syntax highlighting and a download button — the visitor's journey ends with the actual artifact.

   Inputs grouped by owner: **Product** (data sheet: variant), **Board** (hardware engineer: shunt, amplifier gain, divider), **Chip** (target profile: V_ref, ADC/DAC bits, clock), **Design choice** (power engineer: switching frequency). Inputs are independent; the tool derives consequences and enforces the relationships engineers already know (sense-range gate between shunt × gain and trip current; staleness gate between f_sw and loop gains). Small dependency diagram (inputs → derived constants → register values) above the list. Output: regenerated header + diff + gates.
4. **Audit** — conformance results on the synthetic corpus; recorded AI classifications from each compared model (replay); model-comparison table. No live AI on the site (a static site can't hold an API key); a serverless function could add it later without changing pages.
5. **How it works** — process map, worked example, limitations.

Limits: no uploads, no secrets, no server. Requires the repo to be public (free Pages), which happens at launch; before launch Tim reviews locally (`uv run calgen site --serve` → localhost, viewed in the browser pane).

### 3.1a Layout and math (approved mockups, 2026-10-16)

- **Master–detail** on desktop (playground, review reports, audit): left column = constants list with value + status dot (pass / fail / review); **selected row inverted** (primary fill, light text, ringed dot); hint at the bottom of the list: "Choose a constant to see how it's derived". Right pane = derivation of the selected constant. Keyboard selectable (Tab/Enter).
- **< 768 px:** collapses to a single page with chevron rows. **Print/PDF:** everything expanded, sign-off block at the end.
- **Typeset derivations:** each step shows symbolic formula → values substituted → result, with each input's source underneath (data sheet quote, board, target). Failed checks render in red (e.g., `15.0 ≤ 12.54 ✗`). Rendered with KaTeX (MIT; pre-rendered in the static export).
- **Generated, not hand-written:** `rules.yaml` gives each symbol a LaTeX name; ~100 lines of Python turn the formula AST into LaTeX. A test asserts the LaTeX-rendered expression and the evaluator produce the same number. README worked example uses GitHub-native math.
- Audit page uses the same layout: right pane shows the finding, the AI classification, and its evidence.

### 3.2 Mandatory notice — top of page 1, every page footer

> **Results are representative and informational only.** Under Texas Instruments' C2000 software license terms, real TI SDK source code is confidential and licensed for internal use only, so no TI code is included, displayed, processed, or emitted here. All C code on this site is synthetic — written for this demo — with invented names and values that resemble typical power-converter firmware. The generated headers compile against this demo's sample firmware in CI; the "legacy" files used for the audit are illustrative and not guaranteed to compile on any target. Product ratings come from public IntelliPower data sheets; all circuit values and gains are invented. This is an independent demo, not affiliated with or endorsed by AMETEK, IntelliPower, or Texas Instruments. TI, C2000, and Code Composer Studio are trademarks of Texas Instruments.

(Wording note: the restriction is license/copyright/trade-secret, not trademark; the last sentence handles trademarks.)

### 3.3 No-JavaScript fallback

If Pyodide fails to load, pages still show the pre-rendered default product, reports, audit results, and docs; only the live inputs are disabled, with a note.

## 4. Docs

README (front matter: notice, problem 1a–1f, focus, assumptions, unknowns; then process map, demo link, quick start, hand-worked example, audit + eval, limitations, S9 extension paragraph described in general terms, disclaimer). `docs/DESIGN_NOTES.md`, `docs/RESEARCH.md` (public, cited, tactful), `docs/SUMMARY.md` (one page for leaders), `docs/ADDING_A_CONSTANT.md`. Private in jobhunter: `PRIMER.md` for interview prep.

No TI SDK names, values, file layouts, or derived results anywhere in the repo or site. General public facts about TI parts (clock, ADC bits from public datasheets) are fine.

## 5. Tech

Python 3.13 via `uv`. Runtime deps: `pyyaml` (available in Pyodide). Site: static HTML/CSS/JS generated by calgen, KaTeX and Pyodide from a pinned CDN, small JS glue only; the engine package is shipped to the browser as a wheel. Optional `ai` extra: `openai`, `anthropic` (official SDKs). Dev: `pytest`, `hypothesis`. GitHub Actions: pytest + firmware build + known-answer test (ubuntu gcc). `.gitignore` covers `.env`, any `ti-sdk` path. License: all rights reserved, view and evaluate only (changed from MIT on 2026-10-16).

## 6. Milestones (v1 time box ≈ 3 days)

| # | Deliverable | Gate |
|---|---|---|
| M0 | Scaffold, CI skeleton, .gitignore, license | `uv run pytest` green |
| M1 | Spec loading, schema, units, evaluator, number formats | Unit + property tests |
| M2 | Rules → constants (3 variants × revA/B × 2 targets); header gen + marker patch | Determinism, idempotence, hand-worked values |
| M3 | Sample firmware + build + known-answer C test | `make test` green |
| M4 | Data sheet consistency gate on real CSVs | Flags the 3 known issues; no false alarms |
| M5 | Synthetic corpus + blind key (separate agent); conformance audit; staleness gate | Tests green |
| M6 | AI classification: backend interface (replay, openai, anthropic, none), eval harness, model-comparison run (live, cents, after Tim's go), record responses for replay | Offline tests green; comparison table |
| M7 | Review report HTML (master–detail, typeset derivations, print view) + AST→LaTeX + CLI | Reports render; LaTeX/evaluator agreement test |
| M8 | Static site generator + Pyodide playground (notice on page 1), Pages deploy workflow | Runs locally; engine-in-browser outputs match CLI byte-for-byte; deploy only when Tim says |
| M9 | README + docs; calibration add-on if time | Full gate green |

Cut order: calibration → live playground (fall back to pre-rendered products) → second target's reports.

## 7. Done

- Full gate green locally and in CI.
- Site live on GitHub Pages with the notice at the top of page 1.
- Every claim true; no TI SDK material anywhere.
- Repo flipped public and site deployed **only after Tim approves**; deploy costs only when Tim says.
- Hand-off: repo URL, demo URL, 3-line cover-letter summary to the main jobhunter session.

## 8. Open questions for Tim

1. (Decided 2026-10-16: GitHub Pages only, engine in browser; no Railway; no live AI on the site.)
2. GIF/video walkthrough — worth ~30 min?
