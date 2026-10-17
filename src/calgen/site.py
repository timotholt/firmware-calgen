"""Build the static demo site: every page generated from the same engine as the CLI.

    out/site/
      index.html        problem, focus, assumptions, what I don't claim
      playground.html   products + power flow + edit inputs, computed live in the browser (Pyodide)
      audit.html        legacy firmware vs spec, AI classification (recorded), model comparison
      how.html          process map, worked example, limitations
      reports/          one review report per variant
      assets/           site.css, playground.js, calgen bundle, KaTeX, Pyodide (all local)

No page makes a network request outside the site.
"""

from __future__ import annotations

import html
import json
import shutil
from pathlib import Path

from calgen import playground
from calgen.ai import ReplayBackend, classify
from calgen.audit import MATCH, MISMATCH, UNMAPPED, conform, load_map, scan
from calgen.build import build
from calgen.evals import load_key, score
from calgen.latex import derive_check, derive_constant
from calgen.report import CSS as REPORT_CSS
from calgen.report import notice_html, write_report
from calgen.spec import load_rules, load_variant

REPO = "https://github.com/timotholt/firmware-calgen"
VARIANTS = ["fa10507", "fa10449", "fa10434", "fa10507_f2803x", "fa10507_revB"]
NAV = [("index.html", "Overview"), ("playground.html", "Playground"), ("reports/index.html", "Review reports"),
       ("audit.html", "Audit"), ("how.html", "How it works")]

SITE_CSS = REPORT_CSS + """
nav{display:flex;flex-wrap:wrap;gap:4px 18px;border-bottom:1px solid var(--line);padding:10px 0;margin-bottom:6px;font-size:14px}
nav a{color:var(--muted);text-decoration:none}nav a.on{color:var(--fg);font-weight:600}nav .brand{font-weight:700;color:var(--fg);margin-right:8px}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px;margin:14px 0}.card{background:var(--soft);border-radius:10px;padding:12px 14px}
.card h3{margin:0 0 4px;font-size:13px;color:var(--muted);font-weight:500}.card p{margin:0}
a{color:inherit}.btn{display:inline-block;border:1px solid var(--line);border-radius:8px;padding:6px 12px;text-decoration:none;margin:4px 6px 4px 0}
.flowmap{display:flex;flex-wrap:wrap;gap:6px;align-items:center;margin:12px 0}.step{border:1px solid var(--line);border-radius:8px;padding:8px 10px;font-size:13px;background:var(--bg)}
.arrow{color:var(--muted)}
:root{--acc:#185fa5;--accbg:#e6f1fb}@media (prefers-color-scheme:dark){:root{--acc:#85b7eb;--accbg:#0c2c4c}}
.tag{font-size:10px;padding:1px 6px;border-radius:999px;margin-left:4px}.tag-datasheet{background:var(--accbg);color:var(--acc)}.tag-derived{background:var(--soft);color:var(--muted)}.tag-design{background:var(--warnbg);color:var(--warn)}
.fgrid{display:grid;grid-template-columns:minmax(0,1fr) 16px minmax(0,1fr) 16px minmax(0,1fr) 16px minmax(0,1fr) 16px minmax(0,1fr);gap:4px;width:100%;align-items:stretch}
.farrow{display:flex;align-items:center;justify-content:center;color:var(--muted);font-size:16px}.fvert{grid-column:5;text-align:center;color:var(--muted);font-size:16px;line-height:1}
.sum{font-size:11px;color:var(--muted);margin:-2px 0 6px;line-height:1.35}.fb.sel .sum{color:var(--selfg)}
.chg,.r.chg{background:var(--warnbg);color:var(--warn);border-radius:4px}.fb.sel .r.chg{color:var(--selfg);background:transparent;text-decoration:underline}
.was{text-decoration:line-through;opacity:.7}.tag-override{background:var(--badbg);color:var(--bad)}
.sense{font-size:11px;margin:0 0 6px;padding:3px 6px;border-radius:4px;background:var(--okbg);color:var(--ok);line-height:1.35}.sense.bad{background:var(--badbg);color:var(--bad)}
.fb.sel .sense{background:transparent;color:var(--selfg);border:1px solid var(--selfg)}.fb.has-chg{border-color:var(--warn)}.chgpill{background:var(--warnbg);color:var(--warn)}.fb{border:1px solid var(--line);border-radius:8px;padding:8px;font-size:12px;cursor:pointer;background:var(--bg);min-width:0}
.fb:hover{background:var(--soft)}.fb.sel{background:var(--sel);color:var(--selfg)}.fb.bad{border-color:var(--bad)}.fb .t{font-weight:600;margin-bottom:4px}.fb .r{font-family:var(--mono);font-size:11px;line-height:1.5;overflow-wrap:anywhere}
.fb.sel .tag{background:transparent;color:var(--selfg);border:1px solid var(--selfg)}.under{grid-column:5}.tab{cursor:pointer;border:1px solid var(--line);background:var(--bg)}.tab.on{background:var(--sel);color:var(--selfg)}
.inp label{display:block;font-size:12px;color:var(--muted)}.inp input,.inp select{width:100%;font:inherit;padding:4px 6px;border:1px solid var(--line);border-radius:6px;background:var(--bg);color:var(--fg)}
@media (max-width:768px){.fgrid{grid-template-columns:1fr}.farrow{transform:rotate(90deg)}.under,.fvert{grid-column:auto}}ol.problems li{margin:6px 0}h1.hero{font-size:28px;line-height:1.25;margin:24px 0 8px;max-width:30ch}.lead{font-size:19px;line-height:1.5;margin:0 0 24px;max-width:70ch}
.proof{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:16px;border-top:1px solid var(--line);border-bottom:1px solid var(--line);padding:16px 0;margin:0 0 20px}
.proof b{display:block;font-family:var(--mono);font-size:24px;font-weight:600}.proof span{display:block;font-size:13px;color:var(--muted);line-height:1.4}
.cta{display:flex;flex-wrap:wrap;align-items:center;gap:8px 18px;margin:0 0 40px}.cta a{font-size:14px}
.cta a.primary{background:var(--fg);color:var(--bg);border:1px solid var(--fg);border-radius:8px;padding:9px 16px;font-size:15px;font-weight:600;text-decoration:none}
.cards.outlined .card{background:transparent;border:1px solid var(--line);border-radius:8px;padding:16px}
.cards.outlined .card h3{font-size:17px;font-weight:600;color:var(--fg);margin:0 0 6px}.cards.outlined .card p{font-size:15px;color:var(--muted)}
main h2{margin-top:40px}.prose{max-width:75ch}.prose p{margin:0 0 12px}
.more-box{margin-top:40px;border-top:1px solid var(--line);padding-top:12px;font-size:14px}.more-box summary{font-size:15px;color:var(--fg)}
@media (max-width:480px){.proof b{font-size:20px}.proof span{font-size:12px}h1.hero{font-size:24px}.lead{font-size:17px}}
footer{color:var(--muted);font-size:12px;border-top:1px solid var(--line);margin-top:36px;padding-top:10px}
"""


def _e(x: object) -> str:
    return html.escape(str(x))


def _page(title: str, active: str, body: str, depth: int = 0, extra_head: str = "", scripts: str = "") -> str:
    up = "../" * depth
    nav = "".join(f'<a href="{up}{href}" class="{"on" if href == active else ""}">{_e(label)}</a>' for href, label in NAV)
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_e(title)}</title><link rel="stylesheet" href="{up}assets/katex/katex.min.css"><link rel="stylesheet" href="{up}assets/site.css">{extra_head}</head>
<body><main><nav><span class="brand">firmware-calgen</span>{nav}<a href="{REPO}">Source</a></nav>
{notice_html()}
{body}
<footer>Independent demo by Timothy Otholt. Product ratings from public IntelliPower data sheets (cited per value); all circuit values, gains, firmware names, and legacy code are invented. <a href="{REPO}">Source and tests</a>.</footer>
</main><script src="{up}assets/katex/katex.min.js"></script>
<script>document.querySelectorAll('.eq .tex').forEach(function(t){{if(!window.katex)return;var d=document.createElement('div');try{{katex.render(t.textContent,d,{{displayMode:true,throwOnError:false}});t.parentNode.replaceChild(d,t)}}catch(e){{}}}});</script>
{scripts}</body></html>"""


def _script_json(obj: object) -> str:
    """JSON safe to place inside a <script> element (which is not HTML-decoded)."""
    return json.dumps(obj).replace("</", "<\\/").replace("<!--", "<\\u0021--")


def _eqs(lines: list[str]) -> str:
    return "".join(f'<div class="eq"><div class="tex">{_e(x)}</div></div>' for x in lines)


# ---------------------------------------------------------------------------


def page_home() -> str:
    sample = (
        "/* Comparator DAC code for the positive overcurrent trip\n"
        " * = round((target.v_ref / 2 + iout_trip_pk * board.r_shunt * board.g_amp) / target.v_ref * target.dac_max)\n"
        " *   target.v_ref = 3.3 V  [target f28004x.yaml]\n"
        " *   board.r_shunt = 5 mohm  [board ups_ctrl_revA.yaml]\n"
        " *   board.g_amp = 10 ratio  [board ups_ctrl_revA.yaml]\n"
        " *   target.dac_max = 4095 counts  [target f28004x.yaml] */\n"
        "#define UPS_IOUT_TRIP_DAC_HI       3364u          /* 3364 counts, uint16 */"
    )
    body = f"""
<h1 class="hero">Firmware constants, generated from the data sheet and proven before they reach C</h1>
<p class="lead">A working demo for AMETEK IntelliPower's AI Automation Intern posting, initiative 2: automate firmware calibration and configuration constants from engineering specifications. Runs entirely in your browser.</p>
<div class="proof">
<div><b>3</b><span>real IntelliPower data sheets, cited per value</span></div>
<div><b>6 of 33</b><span>legacy constants that disagree with the spec, found by audit</span></div>
<div><b>0</b><span>values written when any gate fails</span></div>
</div>
<p class="cta"><a class="primary" href="playground.html">Open the playground →</a><a href="audit.html">Legacy audit</a><a href="reports/index.html">Review reports</a></p>
<div class="cards outlined">
<div class="card"><h3>The problem I think you have</h3><p>Calibration gains, limits, and register values are hand-edited in C for each product variant and board revision, from data sheets that don't always agree with themselves.</p></div>
<div class="card"><h3>What this demo does</h3><p>Generates those constants from the spec with every number traced to its source, audits existing firmware against the spec, and writes nothing when a gate fails.</p></div>
<div class="card"><h3>What I don't claim</h3><p>Power-electronics design, loop tuning, magnetics, EMI, or certification. Those values come from engineers; the tool carries them safely from spec to source.</p></div>
</div>
<h2>What a generated line looks like</h2>
<pre>{_e(sample)}</pre>
<p class="sub">The formula, every input, and the file each came from travel with the constant. The review report typesets the same derivation, and a test checks that the typeset math equals the computed value.</p>
<h2>Backstory and thesis</h2>
<div class="prose">
<p><b>Backstory.</b> I wrote C firmware and BIOS code at Phoenix Technologies, Quantum, AMD, and VM Labs, where constants had to be exactly right for each specific board. I've come back to engineering through an A.A.S. in AI software engineering, and this posting described a problem I recognized: numbers hand-edited in C source that should come from the spec. I built this demo to show how I'd approach it, before asking for the job.</p>
<p><b>Thesis.</b> IntelliPower publicly describes thousands of configure-to-order variants built from shared designs, and its engineering postings mention keeping legacy boards alive with alternate components. Every variant's ratings and every board's measurement chain must end up as correct constants in firmware; I assume much of that is done by hand today, from data sheets that aren't always consistent (all three I transcribed contain an inconsistency). The right tool makes that path deterministic, traceable, and gated. AI belongs only where the input is messy: here it drafts what each unexplained legacy constant is, scored 91% on category and 97% on units against a blind answer key, and a person reviews every draft. AI never writes firmware.</p>
</div>
<details class="more-box"><summary>The posting, my assumptions, and how I'd check them in week one</summary>
<p>The posting describes six problems: magnetics design iterations, hand-edited firmware constants, specs that aren't machine-usable, provable validation, undocumented process, and responsible AI adoption. This demo addresses the second and supports the next three. It doesn't attempt magnetics; that needs real design data and power-engineering judgment, and a toy would mislead.</p>
<table><tr><th>#</th><th>Assumption</th><th>Why I think so</th><th>Confidence</th><th>How to check</th></tr>
<tr><td>A1</td><td>Calibration and config constants live in C source (#defines / const tables)</td><td>The posting says so</td><td>High</td><td>Read one product's source</td></tr>
<tr><td>A2</td><td>Many constants derive from data sheet ratings</td><td>Data sheet fields map cleanly to limits (1500 VA ÷ 120 V × 1.20 = 15 A)</td><td>Medium</td><td>Trace ten constants to their origin</td></tr>
<tr><td>A3</td><td>Alternate-component substitutions change sense gains</td><td>Engineering postings: "qualify new, or alternate components"</td><td>Medium</td><td>Ask how the last substitution was handled</td></tr>
<tr><td>A4</td><td>The processor is a TI C2000 part</td><td>Posting asks for TI chipsets; public site says DSP firmware</td><td>Medium</td><td>Look at a board</td></tr>
<tr><td>A5</td><td>Specs are not machine-readable today</td><td>All three data sheets checked contain an internal inconsistency</td><td>Medium</td><td>See the spec source of truth</td></tr>
<tr><td>A6</td><td>Some calibration is per unit at a test station</td><td>The phrase "calibration gains"</td><td>Low</td><td>Ask production test</td></tr>
</table></details>
"""
    return _page("firmware-calgen: data sheet to firmware constants", "index.html", body)


def page_reports(out: Path, specs: Path, rules) -> str:
    rows = []
    reports = out / "reports"
    for name in VARIANTS:
        b = build(load_variant(specs / "variants" / f"{name}.yaml"), rules)
        committed = specs.parent / "firmware" / "include" / f"calgen_{name}.h"
        write_report(b, reports, committed.read_text(encoding="utf-8") if committed.exists() else "", katex_path="../assets/katex", back="index.html")
        v = b.variant
        status = '<span class="pill ok">all gates pass</span>' if b.ok else f'<span class="pill bad">{len(b.failures)} failure(s), nothing written</span>'
        rows.append(f'<tr><td><a href="{_e(name)}.html" class="mono">{_e(name)}</a></td><td>{_e(v.datasheet.part)}</td><td>rev {_e(v.board.extra.get("rev"))}</td><td>{_e(v.target.name)}</td><td>{status}</td><td class="sub">{_e(v.path.read_text().split("description:")[1].split(chr(10))[0].strip() if "description:" in v.path.read_text() else "")}</td></tr>')
    body = f"""<h1>Review reports</h1><p class="sub">One report per variant: the document an engineer signs. Click a constant to see its derivation, sources, and generated C. Print for a sign-off copy.</p>
<table><tr><th>Variant</th><th>Product</th><th>Board</th><th>Target</th><th>Result</th><th>Scenario</th></tr>{''.join(rows)}</table>
<p class="sub">Rev B shows the alternate-component story: the replacement current-sense amplifier has twice the gain, so the 1500 VA unit's trip current no longer fits the sensor's range. The tool refuses to generate and says why. The same board is fine for the 650 VA unit.</p>"""
    return _page("Review reports", "reports/index.html", body, depth=1)


def page_audit(root: Path, specs: Path, rules) -> str:
    corpus = root / "corpus" / "legacy_ups"
    cands = scan(corpus)
    b = build(load_variant(specs / "variants" / "fa10507.yaml"), rules)
    conf = conform(cands, load_map(corpus / "calgen_map.yaml"), b)
    recs = sorted((corpus / "ai_runs").glob("*.json"))
    rows = []
    ai_rows = []
    key = load_key(corpus / "ANSWER_KEY.yaml")
    import yaml

    prices = yaml.safe_load((corpus / "ai_runs" / "prices.yaml").read_text()) if (corpus / "ai_runs" / "prices.yaml").exists() else {}
    answers = {}
    for rec in recs:
        backend = ReplayBackend(rec)
        res = classify(corpus, cands, rules, backend)
        s = score(backend.model, cands, key, res)
        p = prices.get(s.model)
        cost = f"${(s.input_tokens * p['input'] + s.output_tokens * p['output']) / 1e6:.4f}" if p else "—"
        ai_rows.append(f"<tr><td class='mono'>{_e(s.model)}</td><td>{s.pct(s.category):.0f}%</td><td>{s.pct(s.units):.0f}%</td><td>{s.pct(s.typed):.0f}%</td><td>{s.pct(s.rule):.0f}%</td><td>{s.answered}/{s.n}</td><td>{cost}</td><td>{s.latency_s:.0f} s</td></tr>")
        if not answers:
            for r in res:
                for item in r.items:
                    answers[(r.file, item.id)] = item
    from calgen.ai import candidate_id

    per_file: dict[str, int] = {}
    for r in conf:
        c = r.candidate
        n = per_file.get(c.file, 0)
        per_file[c.file] = n + 1
        a = answers.get((c.file, candidate_id(c, n)))
        ai_txt = f"{_e(a.category)} · {_e(a.units)} · {_e(a.maps_to_rule or 'no rule')}<br><span class='sub'>{_e(a.reason)}</span>" if a else "—"
        if r.status == MATCH:
            verdict = f'<span class="pill ok">match</span><br><span class="sub mono">{_e(r.rule)}</span>'
        elif r.status == MISMATCH:
            verdict = f'<span class="pill bad">mismatch</span><br><span class="sub">spec: {r.expected:.6g} ({_e(r.rule)})</span>'
        else:
            verdict = '<span class="pill na">not in spec</span>'
        rows.append(f"<tr><td class='mono'>{_e(c.file)}:{c.line}</td><td class='mono'>{_e(c.symbol)}</td><td class='mono'>{_e(c.literal)}</td><td>{verdict}</td><td>{ai_txt}</td></tr>")
    n_match = sum(r.status == MATCH for r in conf)
    n_mis = sum(r.status == MISMATCH for r in conf)
    n_un = sum(r.status == UNMAPPED for r in conf)
    files = "".join(
        f"<details><summary>{_e(f.name)} ({len(f.read_text().splitlines())} lines)</summary><pre>{_e(chr(10).join(f'{i:3d}  {x}' for i, x in enumerate(f.read_text().splitlines(), 1)))}</pre></details>"
        for f in sorted(corpus.glob("*.[ch]"))
    )
    body = f"""<h1>Audit: legacy firmware against the spec</h1>
<p class="sub">The realistic week-one task: before generating anything, read the firmware that exists and compare it to the data sheet. Read-only; nothing is changed.</p>
<div class="cards"><div class="card"><h3>Constants found</h3><p style="font-size:22px">{len(cands)}</p></div><div class="card"><h3>Match the spec</h3><p style="font-size:22px">{n_match}</p></div>
<div class="card"><h3>Disagree with the spec</h3><p style="font-size:22px;color:var(--bad)">{n_mis}</p></div><div class="card"><h3>Not covered by a rule</h3><p style="font-size:22px">{n_un}</p></div></div>
<p>The legacy code below is <b>synthetic</b>: written for this demo by a separate agent under clean-room rules, with seeded mistakes, traps (a 5000&nbsp;ms timeout that equals the correct 5000-count PWM period), and an answer key the classifier never sees. Note the duplicate the audit surfaces: <span class="mono">I_TRIP_RMS = 14.0</span> in one file and <span class="mono">k_trip_a = 15.0</span> in another.</p>
{files}
<h2>Every constant</h2>
<p class="sub">Verdict is deterministic (no AI). The last column is the AI draft: what a model thinks each number is, for a reviewer to accept or correct.</p>
<table><tr><th>Where</th><th>Symbol</th><th>Value</th><th>Spec verdict</th><th>AI draft (recorded)</th></tr>{''.join(rows)}</table>
<h2>AI model comparison</h2>
<p class="sub">Scored against the blind answer key. Bar set before any model ran: ≥ 90% category and ≥ 85% units. Default model is the cheapest that passes. Recorded runs are replayed here; no model is called from this page.</p>
<table><tr><th>Model</th><th>Category</th><th>Units</th><th>Typed vs derived</th><th>Rule mapping</th><th>Valid answers</th><th>Cost / run</th><th>Latency</th></tr>{''.join(ai_rows)}
<tr><td class="mono">claude-haiku-5-5</td><td colspan="7" class="sub">not recorded yet (no Anthropic API key available at recording time)</td></tr>
<tr><td class="mono">claude-sonnet-5-5</td><td colspan="7" class="sub">not recorded yet</td></tr></table>
<p class="sub">Honest history: the first recorded run scored 39% on category. Two bugs in my harness caused it: the model dropped an id suffix, and per-file ids collided during scoring. Both are fixed and covered by tests; ids are now constrained by the output schema. The first run is kept in the repository.</p>
<h2>How the AI is used, and where it is not</h2>
<ul><li>The model sees one file at a time and answers in a strict JSON schema; every answer is validated.</li>
<li>Its output is a draft mapping for review. It never edits firmware or specs.</li>
<li>The firmware path (spec → constants → gates → C) never calls a model.</li>
<li>On controlled data (vendor-confidential, CUI, ITAR), run a local model behind the same interface, or turn the step off.</li></ul>"""
    return _page("Legacy firmware audit", "audit.html", body)


def page_how(specs: Path, rules) -> str:
    b = build(load_variant(specs / "variants" / "fa10507.yaml"), rules)
    steps = ["iout_rated", "iout_trip", "iout_trip_pk", "iout_fs_pk", "iout_trip_dac_hi"]
    worked = "".join(f"<h3 class='mono' style='font-size:13px'>{_e(b.constant(s).rule.symbol)}</h3>{_eqs(derive_constant(b, s).lines)}" for s in steps)
    worked += f"<h3 class='mono' style='font-size:13px'>check iout_sense_range</h3>{_eqs(derive_check(b, 'iout_sense_range').lines)}"
    flow = "".join(
        f'<span class="step">{_e(s)}</span>' + ('<span class="arrow">→</span>' if i < 6 else "")
        for i, s in enumerate(["Data sheet (CSV, cited)", "Consistency gate", "Board + chip + design", "Rules → constants", "Range, overflow, staleness, checks", "C header or marked-block patch", "Compile + known-answer test → review report"])
    )
    body = f"""<h1>How it works</h1>
<div class="flowmap">{flow}</div>
<p>Any gate failure stops the line: nothing is written, and the report says which input caused it.</p>
<h2>Engineering principles</h2>
<ol><li><b>Single source of truth.</b> Generated C is never hand-edited; a test fails if it is.</li>
<li><b>Traceability.</b> Every constant cites its formula and inputs, down to the data sheet quote.</li>
<li><b>Units are checked.</b> A formula that adds volts to amps is an error.</li>
<li><b>Numeric honesty.</b> Stated rounding, overflow is an error not a saturation, quantization error reported.</li>
<li><b>Fail closed.</b> Any failure, nothing written.</li>
<li><b>Deterministic.</b> Same inputs, byte-identical output, so diffs show only real changes.</li>
<li><b>Separation of concerns.</b> Product, board, chip, and engineer design choices are independent inputs.</li>
<li><b>Evidence, not assertion.</b> Hand-worked known answers are checked in C on every build.</li>
<li><b>Human authority.</b> AI drafts; people approve.</li>
<li><b>Stated limits.</b> See below.</li></ol>
<h2>Worked example: FA10507 overcurrent trip, data sheet to register</h2>
<p class="sub">Inputs: 1500 VA and "Shutdown at 20% Overload" from the public data sheet; shunt and amplifier from the (invented) board; reference and DAC width from the chip profile. Check it on paper.</p>
{worked}
<h2>Limitations</h2>
<ul><li>No TI hardware or TI compiler was used. The host C compiler (gcc in CI, clang locally) stands in for Code Composer Studio; it cannot catch C28x issues such as 16-bit <span class="mono">char</span>.</li>
<li>Product ratings are public; every circuit value, gain, firmware name, and the legacy code are invented.</li>
<li>Formulas are textbook relations, not IntelliPower's design rules. Loop gains are carried, never computed.</li>
<li>"Shutdown at 20% Overload" is read as a trip at 120% of rated; FA10434's swapped labels are resolved by a written override that a reviewer must confirm.</li>
<li>The AI eval runs on a synthetic corpus; it measures the pipeline, not real-world accuracy.</li>
<li>Per-unit calibration (test-station trims stored in EEPROM or flash) is a separate path not built here.</li></ul>
<h2>Extension: changing processors</h2>
<p>TI publishes migration guides between C2000 generations. A processor change mostly moves clocks, pin and peripheral assignments, and number formats rather than the physics. Because the chip is a separate input here, a port is "swap the target profile, regenerate, diff": the F2803x-class profile in this demo regenerates the same product in IQ20 fixed point, and the IQ24 overflow of a 265&nbsp;V limit is caught as an error.</p>"""
    return _page("How it works", "how.html", body)


def page_playground(default: dict) -> str:
    opts = playground.options()
    body = f"""<h1>Playground</h1>
<p class="sub">Pick a product, change the board or a design choice, and watch the firmware constants, gates, and generated C follow. Computed in your browser by the same Python code as the command-line tool. Nothing is uploaded.</p>
<div id="engine" class="sub">Showing pre-computed results · loading the in-browser engine…</div>
<div class="md" style="grid-template-columns:200px minmax(0,1fr)">
<div class="list" id="products"></div>
<div><div id="flow" class="flowmap"></div>
<div id="inputs" class="cards" style="margin-top:4px"></div></div></div>
<div id="gates" class="pills"></div><div id="failmsg"></div>
<div class="md"><div class="list"><div id="clist"></div><div class="hint">Choose a constant to see how it's derived</div></div>
<div class="detail"><div class="pills" id="tabs"></div><div id="cdetail"></div></div></div>
<script id="default-data" type="application/json">{_script_json(default)}</script>
<script id="options" type="application/json">{_script_json(opts)}</script>"""
    scripts = '<script src="assets/pyodide/pyodide.js"></script><script src="assets/playground.js"></script>'
    return _page("Playground", "playground.html", body, scripts=scripts)


def bundle(root: Path) -> dict[str, str]:
    """Source files the browser engine needs, as {relative path: text}."""
    files = {}
    for p in sorted((root / "src" / "calgen").glob("*.py")):
        files[f"src/calgen/{p.name}"] = p.read_text(encoding="utf-8")
    for p in sorted((root / "specs").rglob("*")):
        if p.is_file() and p.suffix in (".yaml", ".csv"):
            files[str(p.relative_to(root))] = p.read_text(encoding="utf-8")
    return files


def build_site(root: Path, out: Path, vendor_cache: Path, download: bool = False) -> Path:
    from calgen.vendor import stage

    specs = root / "specs"
    rules = load_rules(specs / "rules.yaml")
    if out.exists():
        shutil.rmtree(out)
    assets = out / "assets"
    stage(vendor_cache, assets, download=download)
    (assets / "site.css").write_text(SITE_CSS, encoding="utf-8")
    shutil.copyfile(Path(__file__).with_name("playground.js"), assets / "playground.js")
    (assets / "calgen_bundle.json").write_text(json.dumps(bundle(root)), encoding="utf-8")
    (out / "index.html").write_text(page_home(), encoding="utf-8")
    (out / "reports").mkdir(parents=True, exist_ok=True)
    (out / "reports" / "index.html").write_text(page_reports(out, specs, rules), encoding="utf-8")
    (out / "audit.html").write_text(page_audit(root, specs, rules), encoding="utf-8")
    (out / "how.html").write_text(page_how(specs, rules), encoding="utf-8")
    (out / "playground.html").write_text(page_playground(playground.run(specs)), encoding="utf-8")
    (out / ".nojekyll").write_text("", encoding="utf-8")
    return out
