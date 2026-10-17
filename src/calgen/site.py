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
.tag{font-size:10px;padding:1px 6px;border-radius:999px;margin-left:4px}.tag-datasheet{background:var(--accbg);color:var(--acc)}.tag-derived{background:var(--soft);color:var(--muted)}.tag-design{background:var(--warnbg);color:var(--warn)}.tag-assumption{background:transparent;color:var(--warn);border:1px dashed var(--warn)}
.ptabs{display:flex;flex-wrap:wrap;gap:0;border-bottom:1px solid var(--line);margin:12px 0 0}
.ptab{padding:10px 16px;cursor:pointer;border:1px solid transparent;border-bottom:0;border-radius:8px 8px 0 0;margin-bottom:-1px;font-size:14px;background:transparent;color:var(--muted)}
.ptab b{display:block;font-family:var(--mono);color:var(--fg);font-size:14px}.ptab:hover{background:var(--soft)}
.ptab.on{border-color:var(--line);background:var(--bg);color:var(--fg)}.ptab.on b{color:var(--fg)}
.statusbar{position:sticky;top:0;z-index:5;background:var(--bg);border-bottom:1px solid var(--line);padding:8px 0;display:flex;flex-wrap:wrap;gap:4px 16px;align-items:center}
.statusbar .pills{margin:0}.statusbar{min-height:44px}
.probpill{border:0;cursor:pointer;font:inherit;font-size:12px}
.stages .fb{position:relative}
.fb .probs{position:absolute;left:6px;right:6px;top:calc(100% - 10px);z-index:4;padding:8px 26px 8px 10px;border-radius:8px;background:var(--bg);color:var(--bad);border:1px solid var(--bad);box-shadow:0 6px 18px rgba(0,0,0,.25);font-size:12px;line-height:1.4;animation:probin .2s ease-out}
.fb .probs ul{margin:0;padding-left:16px}
.howfix{margin-top:8px;padding-top:6px;border-top:1px solid var(--line);color:var(--fg)}.howfix p{margin:4px 0;color:var(--muted)}
.applyfix{display:block;width:100%;text-align:left;margin-top:6px;font:inherit;font-size:12px;padding:6px 8px;border-radius:6px;border:1px solid var(--ok);background:var(--okbg);color:var(--ok);cursor:pointer}
.applyfix:hover{filter:brightness(1.1)}.probx{position:absolute;top:4px;right:6px;border:0;background:transparent;color:var(--bad);font-size:16px;line-height:1;cursor:pointer}
@keyframes probin{from{opacity:0;transform:translateY(-4px)}to{opacity:1;transform:none}}
@media (prefers-reduced-motion:reduce){.fb .probs{animation:none}}
.pg{display:grid;grid-template-columns:minmax(260px,340px) minmax(0,1fr);grid-template-areas:"stages ins" "stages fms";grid-template-rows:auto 1fr;gap:16px 24px;margin-top:16px}
.stages{grid-area:stages}.ins{grid-area:ins}.fms{grid-area:fms}
.colhead{font-size:11px;text-transform:uppercase;letter-spacing:.06em;color:var(--muted);margin:0 0 8px}
.stages .fb{margin:0}.vdown{text-align:center;color:var(--muted);font-size:16px;line-height:1;margin:4px 0}
.busrow{display:grid;grid-template-columns:minmax(0,1fr) 22px minmax(0,0.9fr);align-items:center;gap:0}.side{color:var(--muted);text-align:center}
.inputs{display:block;margin-bottom:20px}.inrow{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:10px;margin-top:10px}
.dshead{display:flex;flex-wrap:wrap;gap:6px 16px;align-items:flex-end;justify-content:space-between;margin-bottom:6px}.dshead h3{margin:0}
.dsgrid{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:4px 16px}.glabel{font-size:11px;text-transform:uppercase;letter-spacing:.06em;color:var(--muted);margin:6px 0 2px}
.inp{display:grid;grid-template-columns:minmax(0,1fr) 68px 28px;align-items:center;gap:6px;margin:3px 0;font-size:13px}.inp span{color:var(--muted)}.inp .u{font-style:normal;color:var(--muted);font-size:12px;white-space:nowrap}
.inp.preset{grid-template-columns:auto 230px}
.inp input,.inp select{width:100%;box-sizing:border-box;font:inherit;font-size:13.5px;height:30px;padding:0 8px;border:1px solid var(--line);border-radius:6px;background:var(--bg);color:var(--fg)}
.inp input::placeholder{color:var(--muted);font-size:11px}.inp.edited input{border-color:var(--warn);background:var(--warnbg)}
.card .inp:has(select){grid-template-columns:minmax(0,1fr) 190px}
select{appearance:none;-webkit-appearance:none;padding-right:30px!important;background-repeat:no-repeat;background-position:right 10px center;background-size:12px 12px;
background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 12 12'%3E%3Cpath d='M2 4l4 4 4-4' fill='none' stroke='%235f5e5a' stroke-width='1.6'/%3E%3C/svg%3E")}
@media (prefers-color-scheme:dark){select{background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 12 12'%3E%3Cpath d='M2 4l4 4 4-4' fill='none' stroke='%23a3a19a' stroke-width='1.6'/%3E%3C/svg%3E")}}
.fb .r{display:flex;flex-wrap:wrap;gap:0 6px;align-items:baseline}.fb .r .lbl{min-width:96px;color:var(--muted);font-family:system-ui,sans-serif;font-size:11.5px}
.busrow .fb .r .lbl{min-width:0;flex-basis:100%}.fb .r .rv{white-space:nowrap}.fb.sel .r .lbl{color:var(--selfg)}
.tag{border:0!important;background:transparent!important;padding:0 2px;font-size:10px}
.legend{margin-top:14px;border:1px solid var(--line);border-radius:8px;padding:10px 12px}.legend table{font-size:12px}.legend td{padding:4px 6px;border-bottom:1px solid var(--line);vertical-align:middle;color:var(--muted)}
.legend td:first-child{white-space:nowrap;width:1%;font-family:var(--mono);color:var(--fg)}.legend tr:last-child td{border-bottom:0}
.lgchg{background:var(--warnbg);color:var(--warn);border-radius:4px;padding:0 4px}.lgbad{border:1px solid var(--bad);color:var(--bad);border-radius:4px;padding:0 4px;font-family:system-ui,sans-serif}
.inputs .card{background:transparent;border:1px solid var(--line);border-radius:8px;padding:10px 12px}.inputs .card h3{font-size:13px;color:var(--fg);font-weight:600;margin:0 0 6px}
.frow{border-bottom:1px solid var(--line)}.frow>button{all:unset;box-sizing:border-box;display:flex;width:100%;gap:8px;align-items:center;padding:8px 4px;cursor:pointer;font-family:var(--mono);font-size:12.5px}
.frow>button:focus-visible{outline:2px solid var(--fg)}.frow .chev{width:12px;color:var(--muted)}.frow .sym{flex:1;min-width:0;overflow-wrap:anywhere}.frow .val{color:var(--muted)}
.frow.open>button{background:var(--sel);color:var(--selfg)}.frow.open>button .val,.frow.open>button .chev{color:var(--selfg)}
.fbody{padding:8px 4px 14px}
@media (max-width:820px){.pg{grid-template-columns:1fr;grid-template-areas:"ins" "stages" "fms"}}
.fgrid{display:grid;grid-template-columns:minmax(0,1fr) 16px minmax(0,1fr) 16px minmax(0,1fr) 16px minmax(0,1fr) 16px minmax(0,1fr);gap:4px;width:100%;align-items:stretch}
.farrow{display:flex;align-items:center;justify-content:center;color:var(--muted);font-size:16px}.fvert{grid-column:5;text-align:center;color:var(--muted);font-size:16px;line-height:1}
.sum{font-size:11px;color:var(--muted);margin:-2px 0 6px;line-height:1.35}.fb.sel .sum{color:var(--selfg)}
.chg,.r.chg{background:var(--warnbg);color:var(--warn);border-radius:4px}.fb.sel .r.chg{color:var(--selfg);background:transparent;text-decoration:underline}
.was{text-decoration:line-through;opacity:.7}
@keyframes calflash{0%,40%{background:var(--fg);color:var(--bg);box-shadow:0 0 0 3px var(--fg)}100%{box-shadow:0 0 0 0 transparent}}
.flash{animation:calflash 1.1s ease-out 1;border-radius:4px}
@media (prefers-reduced-motion:reduce){.flash{animation:none;outline:2px solid var(--warn)}}.tag-override{background:var(--badbg);color:var(--bad)}
.sense{font-size:11px;margin:0 0 6px;padding:3px 6px;border-radius:4px;background:var(--okbg);color:var(--ok);line-height:1.35}.sense.bad{background:var(--badbg);color:var(--bad)}
.fb.sel .sense{background:transparent;color:var(--selfg);border:1px solid var(--selfg)}.fb.has-chg{border-color:var(--warn)}.chgpill{background:var(--warnbg);color:var(--warn)}.fb{border:1px solid var(--line);border-radius:8px;padding:8px;font-size:12px;cursor:pointer;background:var(--bg);min-width:0}
.fb:hover{background:var(--soft)}.fb.sel{background:var(--sel);color:var(--selfg)}.fb.bad{border-color:var(--bad)}.fb .t{font-weight:600;margin-bottom:4px}.fb .r{font-family:var(--mono);font-size:11px;line-height:1.5;overflow-wrap:anywhere}
.fb.sel .tag{background:transparent;color:var(--selfg);border:1px solid var(--selfg)}.under{grid-column:5}.tab{cursor:pointer;border:1px solid var(--line);background:var(--bg)}.tab.on{background:var(--sel);color:var(--selfg)}
.inp label{display:block;font-size:12px;color:var(--muted)}.inp input,.inp select{width:100%;font:inherit;padding:4px 6px;border:1px solid var(--line);border-radius:6px;background:var(--bg);color:var(--fg)}
@media (max-width:768px){.fgrid{grid-template-columns:1fr}.farrow{transform:rotate(90deg)}.under,.fvert{grid-column:auto}}ol.problems li{margin:6px 0}h1.hero{font-size:28px;line-height:1.25;margin:24px 0 8px;max-width:38ch;text-wrap:balance}.lead{font-size:19px;line-height:1.5;margin:0 0 24px;max-width:70ch}
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
<title>{_e(title)}</title><meta name="robots" content="noai, noimageai"><meta name="tdm-reservation" content="1"><meta name="tdm-policy" content="https://github.com/timotholt/firmware-calgen/blob/main/LICENSE"><link rel="stylesheet" href="{up}assets/katex/katex.min.css"><link rel="stylesheet" href="{up}assets/site.css">{extra_head}</head>
<body><main><nav><span class="brand">firmware-calgen</span>{nav}<a href="{REPO}">Source</a></nav>
{notice_html()}
{body}
<footer>© 2026 Timothy Otholt. All rights reserved: you may view and run this demo to evaluate my work; no copying, reuse, or AI training (<a href="{up}LICENSE.txt">license</a>, <a href="{up}THIRD_PARTY_NOTICES.md">third-party notices</a>). Independent demo; product ratings from public IntelliPower data sheets (cited per value); all circuit values, gains, firmware names, and legacy code are invented. <a href="{REPO}">Source and tests</a>.</footer>
</main><script src="{up}assets/katex/katex.min.js"></script>
<script>document.querySelectorAll('.eq .tex').forEach(function(t){{if(!window.katex)return;var d=document.createElement('div');try{{katex.render(t.textContent,d,{{displayMode:true,throwOnError:false}});t.parentNode.replaceChild(d,t)}}catch(e){{}}}});</script>
{scripts}</body></html>"""


def _script_json(obj: object) -> str:
    """JSON safe to place inside a <script> element (which is not HTML-decoded)."""
    return json.dumps(obj).replace("</", "<\\/").replace("<!--", "<\\u0021--")


def _eqs(lines: list[str]) -> str:
    return "".join(f'<div class="eq"><div class="tex">{_e(x)}</div></div>' for x in lines)


# ---------------------------------------------------------------------------


def page_home(counts: dict[str, int], ai: dict[str, float]) -> str:
    sample = (
        "/* Comparator DAC code for the positive hardware peak-current limit\n"
        " * = round((target.v_ref / 2 + iout_pk_limit * board.r_shunt * board.g_amp) / target.v_ref * target.dac_max)\n"
        " *   target.v_ref = 3.3 V  [target f28004x.yaml]\n"
        " *   board.r_shunt = 2 mohm  [board ups_ctrl_revA.yaml]\n"
        " *   board.g_amp = 10 ratio  [board ups_ctrl_revA.yaml]\n"
        " *   target.dac_max = 4095 counts  [target f28004x.yaml] */\n"
        "#define UPS_IOUT_PKLIM_DAC_HI      3133u          /* 3133 counts, uint16 */"
    )
    body = f"""
<h1 class="hero">From data sheet to firmware C code, with every constant traced and checked</h1>
<p class="lead">A working demo for AMETEK IntelliPower's AI Automation Intern posting, initiative 2: automate firmware calibration and configuration constants from engineering specifications. Runs entirely in your browser.</p>
<div class="proof">
<div><b>3</b><span>real IntelliPower data sheets, cited per value</span></div>
<div><b>{counts['contradicts']} of {counts['total']}</b><span>legacy constants that contradict the data sheet, found by audit (+{counts['differs']} that differ from design values)</span></div>
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
<p><b>Thesis.</b> IntelliPower publicly describes thousands of configure-to-order variants built from shared designs, and its engineering postings mention keeping legacy boards alive with alternate components. Every variant's ratings and every board's measurement chain must end up as correct constants in firmware; I assume much of that is done by hand today, from data sheets that aren't always consistent (all three I transcribed contain an inconsistency). The right tool makes that path deterministic, traceable, and gated. AI belongs only where the input is messy: here it drafts what each legacy constant is, and a person reviews every draft. Measured against a blind answer key, the cheapest model maps constants to the right rule {ai['rule']:.0f}% of the time but its category labels reach only {ai['category']:.0f}%, below the bar I set in advance, and I report that rather than move the bar. AI never writes firmware.</p>
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


BAR_CATEGORY, BAR_UNITS = 90.0, 85.0


def audit_results(root: Path, specs: Path, rules):
    corpus = root / "corpus" / "legacy_ups"
    cands = scan(corpus)
    b = build(load_variant(specs / "variants" / "fa10507.yaml"), rules)
    return corpus, cands, conform(cands, load_map(corpus / "calgen_map.yaml"), b)


def audit_counts(conf) -> dict[str, int]:
    return {
        "total": len(conf),
        "match": sum(r.status == MATCH for r in conf),
        "contradicts": sum(r.status == MISMATCH and r.basis == "data sheet" for r in conf),
        "differs": sum(r.status == MISMATCH and r.basis != "data sheet" for r in conf),
        "unexplained": sum(r.status == UNMAPPED for r in conf),
    }


def model_runs(corpus: Path, cands, rules) -> dict[str, list]:
    """model -> list of (score, results) over recorded runs."""
    key = load_key(corpus / "ANSWER_KEY.yaml")
    out: dict[str, list] = {}
    for rec in sorted((corpus / "ai_runs").glob("*.json")):
        backend = ReplayBackend(rec)
        res = classify(corpus, cands, rules, backend)
        out.setdefault(backend.model, []).append((score(backend.model, cands, key, res), res))
    return out


def page_audit(root: Path, specs: Path, rules) -> str:
    import yaml

    from calgen.ai import candidate_id

    corpus, cands, conf = audit_results(root, specs, rules)
    counts = audit_counts(conf)
    prices_file = corpus / "ai_runs" / "prices.yaml"
    prices = yaml.safe_load(prices_file.read_text()) if prices_file.exists() else {}
    runs = model_runs(corpus, cands, rules)
    ai_rows, answers = [], {}
    for model, rr in runs.items():
        sc = [x[0] for x in rr]

        def stat(f):
            vals = [x.pct(f(x)) for x in sc]
            mean = sum(vals) / len(vals)
            return f"{mean:.0f}%" + (f" <span class='sub'>({min(vals):.0f}–{max(vals):.0f})</span>" if len(vals) > 1 else "")

        cat_mean = sum(x.pct(x.category) for x in sc) / len(sc)
        unit_mean = sum(x.pct(x.units) for x in sc) / len(sc)
        passes = cat_mean >= BAR_CATEGORY and unit_mean >= BAR_UNITS
        p = prices.get(model)
        cost = f"${sum((x.input_tokens * p['input'] + x.output_tokens * p['output']) / 1e6 for x in sc) / len(sc):.4f}" if p else "—"
        verdict = '<span class="pill ok">passes</span>' if passes else '<span class="pill warn">below bar</span>'
        ai_rows.append(f"<tr><td class='mono'>{_e(model)}</td><td>{len(sc)}</td><td>{stat(lambda x: x.category)}</td><td>{stat(lambda x: x.units)}</td><td>{stat(lambda x: x.typed)}</td><td>{stat(lambda x: x.rule)}</td><td>{cost}</td><td>{verdict}</td></tr>")
        if not answers:
            for r in rr[0][1]:
                for item in r.items:
                    answers[(r.file, item.id)] = item
    rows, per_file = [], {}
    for r in conf:
        c = r.candidate
        n = per_file.get(c.file, 0)
        per_file[c.file] = n + 1
        a = answers.get((c.file, candidate_id(c, n)))
        ai_txt = f"{_e(a.category)} · {_e(a.units)} · {_e(a.maps_to_rule or 'no rule')}<br><span class='sub'>{_e(a.reason)}</span>" if a else "—"
        if r.status == MATCH:
            verdict = f'<span class="pill ok">match</span><br><span class="sub mono">{_e(r.rule)}</span>'
        elif r.status == MISMATCH and r.basis == "data sheet":
            verdict = f'<span class="pill bad">contradicts data sheet</span><br><span class="sub">data sheet gives {r.expected:.6g} ({_e(r.rule)})</span>'
        elif r.status == MISMATCH:
            verdict = f'<span class="pill warn">differs from design value</span><br><span class="sub">current design: {r.expected:.6g} ({_e(r.rule)})</span>'
        else:
            verdict = '<span class="pill na">not in spec</span>'
        rows.append(f"<tr><td class='mono'>{_e(c.file)}:{c.line}</td><td class='mono'>{_e(c.symbol)}</td><td class='mono'>{_e(c.literal)}</td><td>{verdict}</td><td>{ai_txt}</td></tr>")
    files = "".join(
        f"<details><summary>{_e(f.name)} ({len(f.read_text().splitlines())} lines)</summary><pre>{_e(chr(10).join(f'{i:3d}  {x}' for i, x in enumerate(f.read_text().splitlines(), 1)))}</pre></details>"
        for f in sorted(corpus.glob("*.[ch]"))
    )
    body = f"""<h1>Audit: legacy firmware against the spec</h1>
<p class="sub">The realistic week-one task: before generating anything, read the firmware that exists and compare it to the spec. Read-only; nothing is changed.</p>
<div class="cards"><div class="card"><h3>Constants found</h3><p style="font-size:22px">{counts['total']}</p></div><div class="card"><h3>Match the spec</h3><p style="font-size:22px">{counts['match']}</p></div>
<div class="card"><h3>Contradict the data sheet</h3><p style="font-size:22px;color:var(--bad)">{counts['contradicts']}</p></div><div class="card"><h3>Differ from a design value</h3><p style="font-size:22px;color:var(--warn)">{counts['differs']}</p></div><div class="card"><h3>Not covered by a rule</h3><p style="font-size:22px">{counts['unexplained']}</p></div></div>
<p><b>Two kinds of disagreement.</b> A value that <span class="pill bad">contradicts the data sheet</span> is wrong for the product (here: a 220 V output on a 120 V unit, a 14 A overload on a 15 A rating). A value that <span class="pill warn">differs from a design value</span> only disagrees with this demo's invented board and design choices (shunt, bus margin, dead time); it needs a conversation, not a fix. The most important one here: the legacy fast trip at <span class="mono">21.2 A</span> peak sits at the peak of the <i>RMS overload</i> level, so a fully loaded unit feeding 3:1 crest-factor loads would trip; the current design puts the hardware limit at 43.75&nbsp;A and handles overload with a timed RMS check.</p>
<p>The legacy code is <b>synthetic</b>: written for this demo by a separate agent under clean-room rules, with seeded mistakes, traps, and an answer key the classifier never sees. It is also friendlier than real legacy firmware (most constants have comments), which flatters the AI scores below.</p>
{files}
<h2>Every constant</h2>
<p class="sub">Verdicts are deterministic (no AI). The last column is the AI draft: what a model thinks each number is, for a reviewer to accept or correct.</p>
<table><tr><th>Where</th><th>Symbol</th><th>Value</th><th>Verdict</th><th>AI draft (recorded)</th></tr>{''.join(rows)}</table>
<h2>AI model comparison</h2>
<p class="sub">Scored against the blind answer key; mean (min–max) over recorded runs. Bar set before any model ran: mean ≥ {BAR_CATEGORY:.0f}% category and ≥ {BAR_UNITS:.0f}% units. Recorded runs are replayed here; no model is called from this page.</p>
<table><tr><th>Model</th><th>Runs</th><th>Category</th><th>Units</th><th>Typed vs derived</th><th>Rule mapping</th><th>Cost / run</th><th>Verdict</th></tr>{''.join(ai_rows)}
<tr><td class="mono">claude-haiku-5-5</td><td colspan="7" class="sub">not recorded yet (no Anthropic API key available at recording time)</td></tr>
<tr><td class="mono">claude-sonnet-5-5</td><td colspan="7" class="sub">not recorded yet</td></tr></table>
<p class="sub">What this means: the cheapest model maps legacy constants to the right rule almost every time, which is what the audit needs, but its category labels disagree with the key on borderline cases (is a 4095 ADC count "sense full scale" or "other"?) often enough to miss the bar. Under the rule set in advance, no recorded model passes yet; the next step would be a stronger model, not a looser bar. History: an earlier single run scored 91% on category with a different rule set, and the very first run scored 39% because of two harness bugs (fixed and tested). All runs are kept in the repository.</p>
<h2>How the AI is used, and where it is not</h2>
<ul><li>The model sees one file at a time and answers in a strict JSON schema; every answer is validated.</li>
<li>Its output is a draft mapping for review. It never edits firmware or specs.</li>
<li>The firmware path (spec → constants → gates → C) never calls a model.</li>
<li>On controlled data (vendor-confidential, CUI, ITAR), run a local model behind the same interface, or turn the step off.</li></ul>"""
    return _page("Legacy firmware audit", "audit.html", body)


def page_how(specs: Path, rules) -> str:
    b = build(load_variant(specs / "variants" / "fa10507.yaml"), rules)
    steps = ["iout_rated", "iout_trip", "iout_pk_limit", "iout_fs_pk", "iout_pklim_dac_hi"]
    worked = "".join(f"<h3 class='mono' style='font-size:13px'>{_e(b.constant(s).rule.symbol)}</h3>{_eqs(derive_constant(b, s).lines)}" for s in steps)
    worked += "".join(f"<h3 class='mono' style='font-size:13px'>check {k}</h3>{_eqs(derive_check(b, k).lines)}" for k in ("overload_below_pk_limit", "iout_sense_range"))
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
<h2>Worked example: FA10507 current protection, data sheet to register</h2>
<p class="sub">Two layers, as in real inverters. The data sheet's "Shutdown at 20% Overload" is a <b>timed RMS overload</b> handled in software (the delay is a design value; the sheet gives none). Separately, a <b>hardware peak-current limit</b> on the comparator protects against short circuits; it must sit well above rated peak current so 3:1 crest-factor loads such as computer power supplies don't trip it, and below the sensor's range. Inputs: 1500 VA and the overload level from the public data sheet; the peak-limit factor, shunt, and amplifier are invented design values; reference and DAC width come from the chip profile. Check it on paper.</p>
{worked}
<h2>Limitations</h2>
<ul><li>Sensing is simplified: dividers and the current shunt are drawn referenced to the controller. On an isolated unit a real design senses on the primary side or through isolation amplifiers or current transformers; the scale-factor math is the same.</li>
<li>One rule set assumes a boost-PFC, DC-bus, inverter topology. Real catalogs span topologies (isolated DC-DC stages, different battery paths) and would need rule sets per platform.</li>
<li>No TI hardware or TI compiler was used. The host C compiler (gcc in CI, clang locally) stands in for Code Composer Studio; it cannot catch C28x issues such as 16-bit <span class="mono">char</span>.</li>
<li>Product ratings are public; every circuit value, gain, firmware name, and the legacy code are invented.</li>
<li>Formulas are textbook relations, not IntelliPower's design rules. Loop gains are carried, never computed.</li>
<li>"Shutdown at 20% Overload" is read as a timed RMS trip at 120% of rated; its delay and the hardware peak-limit factor are invented. FA10434's swapped labels are resolved by a written override that a reviewer must confirm.</li>
<li>The AI eval runs on a synthetic corpus; it measures the pipeline, not real-world accuracy.</li>
<li>Per-unit calibration (test-station trims stored in EEPROM or flash) is a separate path not built here.</li></ul>
<h2>Extension: changing processors</h2>
<p>TI publishes migration guides between C2000 generations. A processor change mostly moves clocks, pin and peripheral assignments, and number formats rather than the physics. Because the chip is a separate input here, a port is "swap the target profile, regenerate, diff": the F2803x-class profile in this demo regenerates the same product in IQ20 fixed point, and the IQ24 overflow of a 265&nbsp;V limit is caught as an error.</p>"""
    return _page("How it works", "how.html", body)


def page_playground(default: dict) -> str:
    opts = playground.options()
    body = f"""<h1>Playground</h1>
<p class="sub">Choose a product, change an input, and watch every stage's firmware constants, gates, and generated C follow. Computed in your browser by the same Python code as the command-line tool; nothing is uploaded.</p>
<div class="ptabs" id="products" role="tablist" aria-label="Product data sheet"></div>
<div class="statusbar"><div id="gates" class="pills"></div><div id="engine" class="sub">Showing pre-computed results · loading the in-browser engine…</div></div>
<div class="pg">
<section class="stages" aria-label="UPS power flow, top to bottom"><div class="colhead">Power flow · click a stage</div><div id="flow"></div></section>
<section class="ins"><div class="colhead">Inputs</div><div id="inputs" class="inputs"></div></section>
<section class="fms"><div class="colhead" id="fhead">Formulas</div><div class="pills" id="tabs"></div><div id="formulas"></div></section>
</div>
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
    corpus, cands, conf = audit_results(root, specs, rules)
    nano = [x[0] for x in model_runs(corpus, cands, rules).get("gpt-5.4-nano", [])]
    ai = {k: (sum(x.pct(getattr(x, k)) for x in nano) / len(nano) if nano else 0.0) for k in ("rule", "category", "units")}
    (out / "index.html").write_text(page_home(audit_counts(conf), ai), encoding="utf-8")
    (out / "reports").mkdir(parents=True, exist_ok=True)
    (out / "reports" / "index.html").write_text(page_reports(out, specs, rules), encoding="utf-8")
    (out / "audit.html").write_text(page_audit(root, specs, rules), encoding="utf-8")
    (out / "how.html").write_text(page_how(specs, rules), encoding="utf-8")
    (out / "playground.html").write_text(page_playground(playground.run(specs)), encoding="utf-8")
    (out / ".nojekyll").write_text("", encoding="utf-8")
    shutil.copyfile(root / "LICENSE", out / "LICENSE.txt")
    shutil.copyfile(root / "THIRD_PARTY_NOTICES.md", out / "THIRD_PARTY_NOTICES.md")
    return out
