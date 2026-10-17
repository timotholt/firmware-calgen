"""Static HTML review report for one build: the document an engineer signs.

Layout (see docs/PLAN.md §3.1a): gate summary, then a master-detail view —
constants list on the left (status dot, inverted selection), derivation on the
right with typeset math, sources, and the generated C line. Below: checks,
data sheet findings, staleness, generated C, diff, and a sign-off block.
Printing expands everything.

The page is self-contained: inline CSS and JS, math rendered by a KaTeX copy
served next to the page (``assets/katex``) when present, plain LaTeX text
otherwise. No network requests.
"""

from __future__ import annotations

import difflib
import html
from pathlib import Path

from calgen.build import BLOCKING, FAIL, OK, SKIPPED, WAIVED, Build
from calgen.codegen import GateError, define_block, header
from calgen.latex import derive_check, derive_constant

NOTICE = (
    "<b>Results are representative and informational only.</b> Under Texas Instruments' C2000 software "
    "license terms, real TI SDK source code is confidential and licensed for internal use only, so no TI code is "
    "included, displayed, processed, or emitted here. All C code on this site is synthetic, written for this demo, "
    "with invented names and values that resemble typical power-converter firmware. The generated headers compile "
    "against this demo's sample firmware in CI; the \"legacy\" files used for the audit are illustrative and not "
    "guaranteed to compile on any target. Product ratings come from public IntelliPower data sheets; all circuit "
    "values and gains are invented. Independent demo, not affiliated with or endorsed by AMETEK, IntelliPower, or "
    "Texas Instruments. TI, C2000, and Code Composer Studio are trademarks of Texas Instruments."
)

CSS = """
:root{--bg:#fff;--fg:#1d1d1b;--muted:#5f5e5a;--line:#d9d7cf;--soft:#f4f3ee;--ok:#2f7a3a;--okbg:#e6f2e2;
--bad:#a32d2d;--badbg:#fbe9e9;--warn:#8a5a00;--warnbg:#fbf0d9;--sel:#1d1d1b;--selfg:#fff;--mono:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}
@media (prefers-color-scheme:dark){:root{--bg:#161615;--fg:#ecebe6;--muted:#a3a19a;--line:#3a3936;--soft:#21201e;
--ok:#8fd19a;--okbg:#1f3322;--bad:#f19c9c;--badbg:#3b1f1f;--warn:#f0c674;--warnbg:#3a2f17;--sel:#ecebe6;--selfg:#161615}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.55 system-ui,-apple-system,Segoe UI,sans-serif}
main{max-width:1100px;margin:0 auto;padding:16px}h1{font-size:22px;font-weight:600;margin:8px 0 2px}h2{font-size:17px;font-weight:600;margin:28px 0 8px}
.sub{color:var(--muted);font-size:13px}.mono{font-family:var(--mono);font-size:12.5px}
.notice{background:var(--warnbg);color:var(--warn);border-radius:8px;padding:6px 12px;font-size:12.5px;margin:10px 0 14px}
.notice summary{cursor:pointer;list-style:none}.notice summary::-webkit-details-marker{display:none}
.notice summary .more{text-decoration:underline;margin-left:6px;font-weight:400}.notice[open] summary .more{display:none}.notice p{margin:6px 0 2px}
.pills{display:flex;flex-wrap:wrap;gap:6px;margin:12px 0}.pill{font-size:12px;padding:3px 10px;border-radius:999px}
.ok{background:var(--okbg);color:var(--ok)}.bad{background:var(--badbg);color:var(--bad)}.warn{background:var(--warnbg);color:var(--warn)}.na{background:var(--soft);color:var(--muted)}
.md{display:grid;grid-template-columns:300px minmax(0,1fr);gap:16px;border-top:1px solid var(--line);padding-top:12px}
.list{border-right:1px solid var(--line);padding-right:10px}.blk{font-size:11px;text-transform:uppercase;letter-spacing:.06em;color:var(--muted);margin:12px 0 4px}
.it{display:flex;justify-content:space-between;gap:8px;align-items:center;padding:6px 8px;border-radius:6px;cursor:pointer;font-family:var(--mono);font-size:12px}
.it:hover{background:var(--soft)}.it.sel{background:var(--sel);color:var(--selfg)}.it .v{color:var(--muted)}.it.sel .v{color:var(--selfg)}
.dot{width:8px;height:8px;border-radius:50%;flex:none}.d-ok{background:var(--ok)}.d-bad{background:var(--bad)}.d-na{background:var(--muted)}.d-warn{background:var(--warn)}
.it.sel .dot{box-shadow:0 0 0 2px var(--selfg)}.hint{font-size:12px;color:var(--muted);border-top:1px solid var(--line);margin-top:10px;padding-top:8px}
.detail{min-width:0}.pane{display:none}.pane.on{display:block}.eq{overflow-x:auto;padding:4px 0}.eq .tex{font-family:var(--mono);font-size:12px;color:var(--muted)}
table{border-collapse:collapse;width:100%;font-size:13px}td,th{text-align:left;padding:6px 8px;border-bottom:1px solid var(--line);vertical-align:top}th{color:var(--muted);font-weight:500;font-size:12px}
pre{background:var(--soft);border-radius:8px;padding:12px;overflow-x:auto;font-size:12px;line-height:1.45}
.add{color:var(--ok)}.del{color:var(--bad)}.sign{display:flex;gap:28px;flex-wrap:wrap;border-top:2px solid var(--fg);margin-top:28px;padding-top:12px;font-size:13px}
.sign span{min-width:220px;border-bottom:1px solid var(--muted);display:inline-block;height:1.2em}
details>summary{cursor:pointer;color:var(--muted);font-size:13px}
@media (max-width:768px){.md{grid-template-columns:1fr}.list{border-right:0}.pane{display:block;border-top:1px solid var(--line);padding-top:8px}}
@media print{.list,.hint{display:none}.md{grid-template-columns:1fr}.pane{display:block!important;break-inside:avoid;border-top:1px solid var(--line)}
.notice,.pill{print-color-adjust:exact;-webkit-print-color-adjust:exact}details{display:block}details>summary{display:none}details>*{display:block}}
"""

JS = """
(function(){
  function show(id){
    document.querySelectorAll('.it').forEach(function(e){var on=e.dataset.id===id;e.classList.toggle('sel',on);e.setAttribute('aria-pressed',on)});
    document.querySelectorAll('.pane').forEach(function(p){p.classList.toggle('on',p.id==='p-'+id)});
  }
  document.querySelectorAll('.it').forEach(function(e){
    e.addEventListener('click',function(){show(e.dataset.id)});
    e.addEventListener('keydown',function(ev){if(ev.key==='Enter'||ev.key===' '){ev.preventDefault();show(e.dataset.id)}});
  });
  var first=document.querySelector('.it.start')||document.querySelector('.it');if(first)show(first.dataset.id);
  if(window.katex){document.querySelectorAll('.eq').forEach(function(el){
    var t=el.querySelector('.tex');if(!t)return;var out=document.createElement('div');
    try{katex.render(t.textContent,out,{displayMode:true,throwOnError:false});el.replaceChild(out,t)}catch(e){}
  })}
})();
"""

NOTICE_SHORT = "Representative results only · all C code here is synthetic · no TI code is included or displayed"


def notice_html() -> str:
    """Collapsed by default: one line visible, full text on toggle; printing expands it."""
    return f'<details class="notice"><summary><b>{NOTICE_SHORT}</b> <span class="more">details</span></summary><p>{NOTICE}</p></details>'


_STATUS = {OK: ("ok", "pass"), FAIL: ("bad", "FAIL"), SKIPPED: ("na", "n/a")}


def _e(x: object) -> str:
    return html.escape(str(x))


def _eqs(lines: list[str]) -> str:
    return "".join(f'<div class="eq"><div class="tex">{_e(line)}</div></div>' for line in lines)


def _diff_html(old: str, new: str, name: str) -> str:
    if not old:
        return '<p class="sub">No previous version to compare against: this is a first generation.</p>'
    if old == new:
        return '<p class="sub">No changes against the committed version.</p>'
    rows = []
    for line in difflib.unified_diff(old.splitlines(), new.splitlines(), f"a/{name}", f"b/{name}", lineterm=""):
        cls = "add" if line.startswith("+") and not line.startswith("+++") else "del" if line.startswith("-") and not line.startswith("---") else ""
        rows.append(f'<span class="{cls}">{_e(line)}</span>')
    return "<pre>" + "\n".join(rows) + "</pre>"


def render_report(b: Build, previous_header: str = "", katex_path: str = "assets/katex", back: str = "") -> str:
    v, ds = b.variant, b.variant.datasheet
    n_ok = sum(c.status == OK for c in b.constants)
    n_fail = sum(c.status == FAIL for c in b.constants)
    k_fail = sum(c.status == FAIL for c in b.checks)
    st_fail = sum(s.status == FAIL for s in b.staleness)
    d_block = sum(d.status == BLOCKING for d in b.datasheet)
    d_flag = len(b.datasheet) - d_block
    pills = [
        ("ok" if not n_fail else "bad", f"Constants {n_ok}/{len(b.constants)}"),
        ("ok" if not k_fail else "bad", f"Checks {'pass' if not k_fail else f'{k_fail} failed'}"),
        ("bad" if d_block else ("warn" if d_flag else "ok"), f"Data sheet {'blocking' if d_block else (f'{d_flag} for review' if d_flag else 'consistent')}"),
        ("ok" if not st_fail else "bad", f"Staleness {'current' if not st_fail else f'{st_fail} stale'}"),
        ("ok" if b.ok else "bad", "Generated" if b.ok else "Nothing written (fail closed)"),
    ]
    try:
        c_text = header(b)
    except GateError:
        c_text = ""

    items, panes = [], []
    failing = [c.rule.id for c in b.constants if c.status == FAIL]
    start_id = failing[0] if failing else (b.constants[0].rule.id if b.constants else "")
    for block_id, title in b.rules.blocks.items():
        consts = [c for c in b.constants if c.rule.block == block_id]
        if not consts:
            continue
        items.append(f'<div class="blk">{_e(title)}</div>')
        for c in consts:
            cls, label = _STATUS[c.status]
            shown = c.enum_ident or (c.encoded.literal if c.encoded else ("—" if c.status == SKIPPED else "fail"))
            start = " start" if c.rule.id == start_id else ""
            items.append(
                f'<div class="it{start}" data-id="{_e(c.rule.id)}" role="button" tabindex="0" aria-pressed="false">'
                f'<span>{_e(c.rule.symbol)}</span><span style="display:flex;gap:6px;align-items:center">'
                f'<span class="v">{_e(shown)}</span><span class="dot d-{cls}" title="{label}"></span></span></div>'
            )
            d = derive_constant(b, c.rule.id)
            src_rows = "".join(
                f"<tr><td class='mono'>{_e(s.name)}</td><td>{_e(s.origin)}</td><td>{_e(s.quote) if s.quote else ''}</td></tr>"
                for s in c.sources
                if s.origin != "constant"
            )
            code = "\n".join(define_block(c)) if c.status in (OK, SKIPPED) else ""
            msg = f'<p class="pill {cls}" style="display:inline-block">{_e(c.message)}</p>' if c.message else ""
            fmt = ""
            if c.encoded:
                err = f", quantization error {c.encoded.rel_error * 100:.3g}%" if c.encoded.rel_error else ""
                fmt = f'<p class="sub">Stored as <span class="mono">{_e(c.fmt)}</span> → <span class="mono">{_e(c.encoded.literal)}</span>{err}; rounding half-to-even.</p>'
            panes.append(
                f'<section class="pane" id="p-{_e(c.rule.id)}"><h3 class="mono" style="margin:0">{_e(c.rule.symbol)}</h3>'
                f'<p class="sub">{_e(c.rule.describe)} · <span class="pill {cls}">{label}</span></p>{msg}{_eqs(d.lines)}{fmt}'
                + (f"<table><tr><th>Input</th><th>From</th><th>Data sheet text</th></tr>{src_rows}</table>" if src_rows else "")
                + (f"<details open><summary>Generated C</summary><pre>{_e(code)}</pre></details>" if code else "")
                + "</section>"
            )

    check_rows = []
    for k in b.checks:
        cls, label = _STATUS[k.status]
        eqs = _eqs(derive_check(b, k.check.id).lines)
        check_rows.append(f'<tr><td><span class="pill {cls}">{label}</span></td><td><b>{_e(k.check.id)}</b><br><span class="sub">{_e(k.check.describe)}</span></td><td>{eqs}</td></tr>')
    ds_rows = []
    for d in b.datasheet:
        cls = {"blocking": "bad", "waived": "warn", "flagged": "warn"}[d.status]
        ev = "<br>".join(f'<span class="mono">“{_e(x)}”</span>' for x in d.finding.evidence)
        ds_rows.append(f'<tr><td><span class="pill {cls}">{_e(d.status)}</span></td><td>{_e(d.finding.message)}<br>{ev}</td><td class="sub">{_e(d.note)}</td></tr>')
    st_rows = []
    for s in b.staleness:
        cls, label = _STATUS[s.status]
        st_rows.append(f'<tr><td><span class="pill {cls}">{label}</span></td><td class="mono">{_e(s.param)}</td><td>designed for {_e(s.against)} = {_e(s.designed)}; now {_e(s.current)}</td></tr>')
    overrides = "".join(f"<li><b>ds.{_e(p.name)}</b>: {_e(' '.join(p.note.split()))}</li>" for p in v.overrides.values())

    title = f"Review: {v.name}"
    doc = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_e(title)}</title><link rel="stylesheet" href="{katex_path}/katex.min.css"><style>{CSS}</style></head><body><main>
{f'<p class="sub"><a href="{back}">← All review reports</a></p>' if back else ''}{notice_html()}
<h1>{_e(title)}</h1>
<div class="sub">{_e(ds.part)} · {_e(ds.params['model_string'].value)} · board {_e(v.board.name)} rev {_e(v.board.extra.get('rev', '?'))} · target {_e(v.target.name)} ({_e(v.target.extra.get('default_format', 'float32'))})</div>
<div class="sub mono">inputs sha256 {_e(b.digest)}</div>
<div class="pills">{''.join(f'<span class="pill {c}">{_e(t)}</span>' for c, t in pills)}</div>
{f'<p><b>Reviewer-visible overrides</b></p><ul>{overrides}</ul>' if overrides else ''}
<h2>Constants</h2>
<div class="md"><div class="list">{''.join(items)}<div class="hint">Choose a constant to see how it's derived</div></div><div class="detail">{''.join(panes)}</div></div>
<h2>Checks</h2><table><tr><th></th><th>Check</th><th>Math</th></tr>{''.join(check_rows)}</table>
<h2>Data sheet consistency</h2>{f'<table><tr><th></th><th>Finding</th><th>Handling</th></tr>{"".join(ds_rows)}</table>' if ds_rows else '<p class="sub">No inconsistencies found in this data sheet.</p>'}
<h2>Staleness of engineer-supplied values</h2><table><tr><th></th><th>Value</th><th>Design basis</th></tr>{''.join(st_rows)}</table>
<h2>Generated C</h2>{f'<details><summary>calgen_{_e(v.name)}.h ({len(c_text.splitlines())} lines)</summary><pre>{_e(c_text)}</pre></details>' if c_text else '<p class="pill bad" style="display:inline-block">Not generated: gates failed, nothing written.</p>'}
<h2>Diff against committed version</h2>{_diff_html(previous_header, c_text, f'calgen_{v.name}.h') if c_text else '<p class="sub">—</p>'}
<div class="sign"><div>Reviewed by <span></span></div><div>Date <span style="min-width:120px"></span></div><div>Decision: approve / reject / waiver</div></div>
</main><script src="{katex_path}/katex.min.js"></script><script>{JS}</script></body></html>
"""
    return doc


def write_report(b: Build, out_dir: Path, previous_header: str = "", katex_path: str = "assets/katex", back: str = "") -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{b.variant.name}.html"
    path.write_text(render_report(b, previous_header, katex_path, back), encoding="utf-8")
    return path


def summary(b: Build) -> dict:
    """Machine-readable gate summary (used by the site index)."""
    return {
        "variant": b.variant.name,
        "part": b.variant.datasheet.part,
        "board_rev": b.variant.board.extra.get("rev"),
        "target": b.variant.target.name,
        "ok": b.ok,
        "failures": b.failures,
        "waived": [d.finding.message for d in b.datasheet if d.status == WAIVED],
    }

