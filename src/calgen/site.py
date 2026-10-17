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

import hashlib
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
NAV = [("index.html", "Overview"), ("magnetics.html", "Magnetics"), ("playground.html", "Firmware"),
       ("audit.html", "Audit"), ("reports/index.html", "Reports"), ("how.html", "How it works"), ("ai.html", "AI practice"),
       ("backstory.html", "Tim Otholt")]

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
.statusbar .pills{margin:0}.statusbar{min-height:44px}.engine{margin:8px 0 0;font-size:12.5px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.probpill{border:0;cursor:pointer;font:inherit;font-size:12px}
.probs{margin:10px 0;padding:10px 12px;border-radius:8px;color:var(--bad);border:1px solid var(--bad);font-size:12.5px;line-height:1.4;animation:probin .2s ease-out}
.probs ul{margin:4px 0 0;padding-left:16px}.pst{margin-top:8px}.pstage{all:unset;cursor:pointer;font-weight:600;color:var(--fg);font-size:12.5px}.pstage:hover{text-decoration:underline}
.ins .dshead{display:block}.ins .inp.preset{grid-template-columns:minmax(0,1fr) 190px}.presetrow{display:flex;flex-direction:column;gap:6px}.presetrow .btn{align-self:flex-end}.presetrow .btn{margin:0;font:inherit;font-size:13px;cursor:pointer;background:var(--bg);color:var(--fg)}
.inp.edited select{border-color:var(--warn);background-color:var(--warnbg)}
.howfix{margin-top:8px;padding-top:6px;border-top:1px solid var(--line);color:var(--fg)}.howfix p{margin:4px 0;color:var(--muted)}
.applyfix{display:block;width:100%;text-align:left;margin-top:6px;font:inherit;font-size:12px;padding:6px 8px;border-radius:6px;border:1px solid var(--ok);background:var(--okbg);color:var(--ok);cursor:pointer}
.applyfix:hover{filter:brightness(1.1)}
@keyframes probin{from{opacity:0;transform:translateY(-4px)}to{opacity:1;transform:none}}
@media (prefers-reduced-motion:reduce){.probs{animation:none}}
.pg{display:grid;grid-template-columns:minmax(320px,420px) minmax(0,1fr);grid-template-areas:"ins stages" "ins fms";grid-template-rows:auto 1fr;gap:16px 28px;margin-top:16px}
.ins{position:sticky;top:60px;align-self:start;max-height:calc(100vh - 72px);overflow:auto;padding-right:4px}
.stages{grid-area:stages}.ins{grid-area:ins}.fms{grid-area:fms}
.colhead{font-size:11px;text-transform:uppercase;letter-spacing:.06em;color:var(--muted);margin:0 0 8px}
.stages .fb{margin:0}.vdown{text-align:center;color:var(--muted);font-size:16px;line-height:1;margin:4px 0}
.busrow{display:grid;grid-template-columns:minmax(0,1fr) 22px minmax(0,0.9fr);align-items:center;gap:0}.side{color:var(--muted);text-align:center}
.inputs{display:block;margin-bottom:20px}.inrow{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:10px;margin-top:10px}
.dshead{display:flex;flex-wrap:wrap;gap:6px 16px;align-items:flex-end;justify-content:space-between;margin-bottom:6px}.dshead h3{margin:0}
.dsgrid{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:4px 16px}.glabel{font-size:11px;text-transform:uppercase;letter-spacing:.06em;color:var(--muted);margin:6px 0 2px}
.inp{display:grid;grid-template-columns:minmax(0,1fr) 68px 28px;align-items:center;gap:6px;margin:3px 0;font-size:13px}.inp span{color:var(--muted)}.inp .u{font-style:normal;color:var(--muted);font-size:12px;white-space:nowrap}
.inp.preset{grid-template-columns:auto 230px}
.inp input,.inp select{width:100%;box-sizing:border-box;font:inherit;font-size:13.5px;height:30px;padding:0 8px;border:1px solid var(--line);border-radius:6px;background-color:var(--bg);color:var(--fg)}
.inp input::placeholder{color:var(--muted);font-size:11px}.inp.edited input{border-color:var(--warn);background:var(--warnbg)}
.card .inp:has(select){grid-template-columns:minmax(0,1fr) 190px}
select{appearance:none;-webkit-appearance:none;padding-right:34px!important;background-repeat:no-repeat;background-position:right 12px center;background-size:12px 12px;
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
.fbody{padding:8px 4px 14px 14px;border-left:3px solid var(--fg);margin-left:2px}
#formulas .frow>button:hover{background:var(--soft)}#formulas .frow>button:hover .sym{text-decoration:underline}#formulas .frow.open>button{background:var(--soft);color:var(--fg);font-weight:600}#formulas .frow.open>button .chev{color:var(--fg)}#formulas .frow.open>button .val{color:var(--muted)}
#formulas .eq{padding:0}#formulas .katex-display{margin:4px 0}#formulas .katex-display>.katex{text-align:left;font-size:1.15em}
#formulas .fbody table{width:auto;max-width:100%;margin-top:10px;font-size:12.5px}#formulas .fbody td,#formulas .fbody th{padding:4px 14px 4px 0}#formulas .fbody td:first-child{white-space:nowrap}
@media (max-width:820px){.pg{grid-template-columns:1fr;grid-template-areas:"ins" "stages" "fms"}.ins{position:static;max-height:none;overflow:visible}}
.fgrid{display:grid;grid-template-columns:minmax(0,1fr) 16px minmax(0,1fr) 16px minmax(0,1fr) 16px minmax(0,1fr) 16px minmax(0,1fr);gap:4px;width:100%;align-items:stretch}
.farrow{display:flex;align-items:center;justify-content:center;color:var(--muted);font-size:16px}.fvert{grid-column:5;text-align:center;color:var(--muted);font-size:16px;line-height:1}
.sum{font-size:11px;color:var(--muted);margin:-2px 0 6px;line-height:1.35}.fb.sel .sum{color:var(--selfg)}
.chg,.r.chg{background:var(--warnbg);color:var(--warn);border-radius:4px}.fb.sel .r.chg{color:var(--selfg);background:transparent;text-decoration:underline}
.was{text-decoration:line-through;opacity:.7}
@keyframes calflash{0%,40%{background:var(--fg);color:var(--bg);box-shadow:0 0 0 3px var(--fg)}100%{box-shadow:0 0 0 0 transparent}}
.flash{animation:calflash 1.1s ease-out 1;border-radius:4px}
@media (prefers-reduced-motion:reduce){.flash{animation:none;outline:2px solid var(--warn)}}.tag-override{background:var(--badbg);color:var(--bad)}
.sense{font-size:11px;margin:0 0 6px;padding:3px 6px;border-radius:4px;border:1px solid transparent;background:var(--okbg);color:var(--ok);line-height:1.35}.sense.bad{background:var(--badbg);color:var(--bad)}
.vizbox{background:var(--bg);color:var(--fg);border:1px solid var(--line);border-radius:6px;padding:6px 8px 2px;margin:6px 0 8px}.viz{display:block;width:100%;height:auto;margin:4px 0 2px;overflow:visible}.g-bar{fill:var(--soft);stroke:var(--line)}.g-head{fill:var(--warnbg)}.g-blind{fill:var(--badbg)}.g-mid{stroke:currentColor;opacity:.5}.g-t{font:11px system-ui,sans-serif;fill:currentColor;opacity:.85}.g-m{stroke:currentColor;opacity:.7}line.g-lim{stroke:currentColor;stroke-width:2.5}line.g-lim.bad,line.w-lim.bad{stroke:var(--bad)}text.g-lim{font-weight:600;opacity:1}text.g-lim.bad{fill:var(--bad)}.w-band{fill:var(--soft);opacity:.6}.w-axis{stroke:currentColor;opacity:.25}.w-ol{stroke:var(--warn);stroke-dasharray:6 4;stroke-width:1.5}.w-lim{stroke:currentColor;stroke-width:2}.w-sine{fill:none;stroke:currentColor;opacity:.35;stroke-width:1.2}.w-load{fill:none;stroke:var(--acc);stroke-width:2}.wkey{display:flex;flex-wrap:wrap;gap:2px 12px;font:10.5px system-ui,sans-serif;opacity:.85;margin:0 0 6px}.wkey i{display:inline-block;width:14px;height:0;vertical-align:middle;margin-right:4px;border-top:2px solid}.k-load{border-color:var(--acc)!important}.k-sine{opacity:.4}.k-ol{border-top:2px dashed var(--warn)!important}.k-lim.bad{border-color:var(--bad)!important}.k-band{height:8px!important;border:0!important;background:var(--soft)}pre.code .c-com{color:var(--muted)}pre.code .c-ovr{color:var(--bad)}pre.code .c-pp{color:var(--acc);font-weight:600}pre.code .c-num{color:var(--warn)}pre.code .c-name{color:var(--fg);font-weight:600}.fb.sel .sense{background:transparent;color:var(--selfg);border:1px solid var(--selfg)}.fb.has-chg{border-color:var(--warn)}.chgpill{background:var(--warnbg);color:var(--warn)}.fb{border:1px solid var(--line);border-radius:8px;padding:8px;font-size:12px;cursor:pointer;background:var(--bg);min-width:0}
.fb:hover{background:var(--soft)}.fb.sel{background:var(--sel);color:var(--selfg)}.fb.bad{border-color:var(--bad)}.fb .t{font-weight:600;margin-bottom:4px}.fb .r{font-family:var(--mono);font-size:11px;line-height:1.5;overflow-wrap:anywhere}
.fb.sel .tag{background:transparent;color:var(--selfg);border:1px solid var(--selfg)}.under{grid-column:5}.tab{cursor:pointer;border:1px solid var(--line);background:var(--bg)}.tab.on{background:var(--sel);color:var(--selfg)}
.inp label{display:block;font-size:12px;color:var(--muted)}.inp input,.inp select{width:100%;font:inherit;padding:4px 6px;border:1px solid var(--line);border-radius:6px;background-color:var(--bg);color:var(--fg)}
@media (max-width:768px){.fgrid{grid-template-columns:1fr}.farrow{transform:rotate(90deg)}.under,.fvert{grid-column:auto}}ol.problems li{margin:6px 0}h1.hero{font-size:28px;line-height:1.25;margin:24px 0 8px}.assume{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:4px 24px;margin:0;padding:0;list-style:none;font-size:14.5px;line-height:1.45}.assume li{padding:8px 0;border-bottom:1px solid var(--line)}.assume b{display:block;font-size:12px;text-transform:uppercase;letter-spacing:.05em;color:var(--muted);font-weight:500}.lead{font-size:19px;line-height:1.5;margin:0 0 24px}
.proof{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:16px;border-top:1px solid var(--line);border-bottom:1px solid var(--line);padding:16px 0;margin:0 0 20px}
.proof b{display:block;font-family:var(--mono);font-size:24px;font-weight:600}.proof span{display:block;font-size:13px;color:var(--muted);line-height:1.4}
.cta{display:flex;flex-wrap:wrap;align-items:center;gap:8px 18px;margin:0 0 40px}.cta a{font-size:14px}
.cta a.primary{background:var(--fg);color:var(--bg);border:1px solid var(--fg);border-radius:8px;padding:9px 16px;font-size:15px;font-weight:600;text-decoration:none}
.cards.outlined .card{background:transparent;border:1px solid var(--line);border-radius:8px;padding:16px}
.cards.outlined .card h3{font-size:17px;font-weight:600;color:var(--fg);margin:0 0 6px}.cards.outlined .card p{font-size:15px;color:var(--muted)}
main h2{margin-top:40px}.prose{max-width:75ch}.prose p{margin:0 0 12px}
.posting{margin:12px 0 16px}.posting .shot{max-height:440px;max-width:760px;overflow-y:auto;border:1px solid var(--line);border-radius:8px;background:#f2f2f2}.posting img{display:block;width:100%;height:auto}.posting figcaption{font-size:12.5px;color:var(--muted);margin-top:6px;max-width:760px}.sblock{border-left:4px solid;border-radius:0 8px 8px 0;padding:14px 18px 2px;margin:0 0 28px}.sblock .slabel{font-size:12px;text-transform:uppercase;letter-spacing:.08em;font-weight:600;margin-bottom:6px}.sblock.back{border-color:var(--warn);background:var(--warnbg)}.sblock.back .slabel{color:var(--warn)}.sblock.why{border-color:var(--ok);background:var(--okbg)}.sblock.why .slabel{color:var(--ok)}.sblock.thesis{border-color:var(--acc);background:var(--accbg)}.sblock.thesis .slabel{color:var(--acc)}.story-page.wide{max-width:80ch}.plan td{vertical-align:top}.plan td:first-child{white-space:nowrap;font-family:var(--mono)}.sblock ul{margin:0 0 16px;padding-left:20px}.sblock li{margin:6px 0}.msearch{display:flex;flex-wrap:wrap;gap:8px 14px;align-items:flex-end;margin:18px 0 6px;font-size:13px}.msearch label{display:flex;flex-direction:column;gap:3px;color:var(--muted)}.msearch .grow{flex:1;min-width:180px}.msearch input,.msearch select{font:inherit;height:30px;padding:0 8px;border:1px solid var(--line);border-radius:6px;background-color:var(--bg);color:var(--fg);width:110px;box-sizing:border-box}.msearch .grow input{width:100%}.msearch select{width:140px}.msearch .btn{margin:0;height:30px;cursor:pointer;background:var(--bg);color:var(--fg);font:inherit}.indlink{font-size:11px;margin:0 0 6px;padding:3px 6px;border-radius:4px;border:1px dashed var(--line);line-height:1.35}.indlink a{font-weight:600}.mfigs{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:16px;margin:8px 0 12px}.mfig{margin:0}.mfig svg{display:block;width:100%;height:auto;max-height:300px}.mfig figcaption{font-size:12px;color:var(--muted);margin-top:4px;line-height:1.4}.mw-core{fill:var(--soft);stroke:var(--muted);stroke-width:.4}.mw-win{fill:var(--bg)}.mw-w0{fill:#c27a3a}.mw-w1{fill:#e3b26b}.mw-cut{stroke:var(--muted);stroke-dasharray:2 2;stroke-width:.3}.mc-ax{stroke:var(--muted)}.mc-l{fill:none;stroke:var(--acc);stroke-width:2}.mc-g{stroke:var(--line);stroke-dasharray:3 3}.mc-req{stroke:var(--warn);stroke-dasharray:6 4;stroke-width:1.5}.mc-pk{stroke:var(--muted);stroke-dasharray:2 3}.mc-dot{fill:var(--acc)}.mc-t{font:11px system-ui,sans-serif;fill:var(--muted)}.mc-reqt{fill:var(--warn)}.sizer{margin-top:28px}.sizer #sz-ret{width:200px}.primary-btn{background:var(--fg)!important;color:var(--bg)!important;font-weight:600}.szt td,.szt th{font-size:12.5px}.szt tr.cand{cursor:pointer}.szt tr.cand:hover{background:var(--soft)}.szt tr.cand.on{background:var(--sel);color:var(--selfg)}.szmath{padding:4px 0 10px}.mlist tr.mrow{cursor:pointer}.mlist tr.mrow:hover{background:var(--soft)}.mlist tr.mrow.on{background:var(--sel);color:var(--selfg)}#m-detail{margin-top:18px;border-top:1px solid var(--line);padding-top:12px}.mdetail{display:grid;grid-template-columns:minmax(0,1.1fr) minmax(0,1fr);gap:18px}.mdraw img{display:block;width:100%;height:auto;border:1px solid var(--line);border-radius:6px;background:#fff}.minfo table{font-size:12.5px}.mcheck{border-bottom:1px solid var(--line);padding:6px 0}.mcheck p{margin:4px 0}.msim li{margin:4px 0}@media (max-width:820px){.mdetail{grid-template-columns:1fr}}.initiatives{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:18px;margin:8px 0 18px}.init{border:1px solid var(--line);border-radius:10px;padding:16px 18px;display:flex;flex-direction:column}.init h2{margin:4px 0 8px;font-size:19px}.kicker{font-size:12px;text-transform:uppercase;letter-spacing:.07em;color:var(--acc);font-weight:600}.init p{margin:0 0 10px;color:var(--fg);line-height:1.5}.thumb{display:flex;justify-content:center;align-items:center;min-height:150px;margin:6px 0 10px}.thumb svg{width:150px;height:150px}.miniflow{flex-wrap:wrap;gap:4px;align-content:center}.ministage{border:1px solid var(--line);border-radius:6px;padding:6px 8px;font-size:12px}.ministage.bad{border-color:var(--bad);color:var(--bad)}.miniarrow{color:var(--muted);margin:0 2px}.mini{list-style:none;padding:0;margin:0 0 12px;font-size:13.5px;color:var(--muted)}.mini li{padding:4px 0;border-bottom:1px solid var(--line)}.mini b{color:var(--fg);font-family:var(--mono)}.init p:last-child{margin-top:auto}.primary-link{display:inline-block;background:var(--fg);color:var(--bg);border-radius:8px;padding:8px 14px;font-weight:600;text-decoration:none;font-size:14px}.connect{border-left:3px solid var(--acc);background:var(--accbg);padding:10px 14px;border-radius:0 8px 8px 0;margin:0 0 18px;line-height:1.5}.key{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px;margin:0 0 8px;font-size:13.5px;color:var(--muted)}.key b{display:block;color:var(--fg);font-size:12px;text-transform:uppercase;letter-spacing:.06em}.story-page{max-width:68ch;margin:56px 0 80px}.story-page h1{font-size:28px;margin:0 0 10px}.prose.roomy{font-size:17px;line-height:1.7}.prose.roomy p{margin:0 0 28px}.more-box{margin-top:40px;border-top:1px solid var(--line);padding-top:12px;font-size:14px}.more-box summary{font-size:15px;color:var(--fg)}
@media (max-width:480px){.proof b{font-size:20px}.proof span{font-size:12px}h1.hero{font-size:24px}.lead{font-size:17px}}
footer{color:var(--muted);font-size:12px;border-top:1px solid var(--line);margin-top:36px;padding-top:10px}
"""


def _e(x: object) -> str:
    return html.escape(str(x))


ASSET_VERSION = ""  # content hash of site.css, playground.js and the engine bundle; set by build_site


def _page(title: str, active: str, body: str, depth: int = 0, extra_head: str = "", scripts: str = "") -> str:
    up = "../" * depth
    nav = "".join(f'<a href="{up}{href}" class="{"on" if href == active else ""}">{_e(label)}</a>' for href, label in NAV)
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_e(title)}</title><meta name="robots" content="noai, noimageai"><meta name="tdm-reservation" content="1"><meta name="tdm-policy" content="https://github.com/timotholt/firmware-calgen/blob/main/LICENSE"><link rel="stylesheet" href="{up}assets/katex/katex.min.css"><link rel="stylesheet" href="{up}assets/site.css?v={ASSET_VERSION}">{extra_head}</head>
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


ASSUMPTIONS_HTML = """<ul class="assume">
<li><b>Processor</b>TI C2000-class: F28004x (floating point, 100 MHz, 12-bit comparator DAC) by default; F2803x (no FPU, IQ20 fixed point, 60 MHz, 10-bit DAC) as the legacy port. The pairing with these products is illustrative.</li>
<li><b>Power stage</b>Double-conversion online UPS: boost PFC rectifier, DC bus, inverter, battery on the bus.</li>
<li><b>Control board</b>Invented current sensing: 2 mΩ shunt, ×10 amplifier, mid-rail biased into a 3.3 V ADC. Rev B swaps in a ×20 amplifier.</li>
<li><b>Design choices</b>Invented: 20 kHz switching, 1 µs dead time, 7% bus margin, 95% sensor headroom, peak limit 3.5 × rated current, 30 s overload delay.</li>
<li><b>Battery</b>LiFePO4 at 2.5 V per cell cutoff and 3.65 V full charge (generic chemistry figures).</li>
<li><b>Where constants live</b>In C headers as <code>#define</code>s, the form the posting implies; other forms (tables, EEPROM images) would only change the output format.</li>
<li><b>Magnetics</b>Design limits are textbook assumptions (current density, window fill, flux margin); inductor requirements use a 30% ripple assumption and first-order formulas; drawings are synthetic.</li>
</ul>"""

GENERATED_SAMPLE = (
    "/* Comparator DAC code for the positive hardware peak-current limit\n"
    " * = round((target.v_ref / 2 + iout_pk_limit * board.r_shunt * board.g_amp) / target.v_ref * target.dac_max)\n"
    " *   target.v_ref = 3.3 V  [target f28004x.yaml]\n"
    " *   board.r_shunt = 2 mohm  [board ups_ctrl_revA.yaml]\n"
    " *   board.g_amp = 10 ratio  [board ups_ctrl_revA.yaml]\n"
    " *   target.dac_max = 4095 counts  [target f28004x.yaml] */\n"
    "#define UPS_IOUT_PKLIM_DAC_HI      3133u          /* 3133 counts, uint16 */"
)


def page_home(counts: dict[str, int], ai: dict[str, float], mag: dict) -> str:
    pfc = mag["pfc"]
    flow = "".join(f'<span class="ministage{" bad" if s == "AC output" else ""}">{s}</span>' + ('<span class="miniarrow">→</span>' if i < 4 else "")
                   for i, s in enumerate(["AC input", "Rectifier / PFC", "DC bus", "Inverter", "AC output"]))
    body = f"""
<h1 class="hero">Both initiatives from AMETEK IntelliPower's AI Automation Intern posting, worked end to end</h1>
<p class="lead">Built with AI agents under my direction, with every number traced to its source and checked before it is used. Runs entirely in your browser.</p>
<div class="initiatives">
<section class="init">
<div class="kicker">Initiative 1 · Magnetics design automation</div>
<h2>Past designs into checked data; requirements into candidate designs</h2>
<p>The posting asks for an AI tool that speeds up inductor and transformer design using past designs. This builds the step that tool needs first: drawings read into structured records, checked against real core data, and searchable, plus a sizing tool that turns a requirement into checked starting designs.</p>
<div class="thumb">{mag["thumb"]}</div>
<ul class="mini"><li><b>{mag["drawings"]}</b> synthetic drawings, read back from PDF</li><li><b>{mag["cores"]}</b> real cores with cited data</li><li>checks agree with the blind key on <b>{mag["agree"]} of {mag["drawings"]}</b></li></ul>
<p><a class="primary-link" href="magnetics.html">Open Magnetics →</a></p>
</section>
<section class="init">
<div class="kicker">Initiative 2 · Firmware modification and calibration</div>
<h2>Data sheets into firmware constants, gated</h2>
<p>Calibration gains, limits, and register values are generated from the product data sheet, the board, and the chip, with every value traced. Gates refuse to write C when anything is inconsistent: try the alternate amplifier on the 1500 VA unit.</p>
<div class="thumb miniflow">{flow}<div class="sub" style="width:100%;margin-top:6px">Rev B on the 1500 VA unit: the sensor saturates before the peak limit fires, so nothing is written.</div></div>
<ul class="mini"><li><b>3</b> real IntelliPower data sheets, cited per value</li><li><b>{counts['contradicts']} of {counts['total']}</b> legacy constants contradict the data sheet</li><li><b>0</b> values written when any gate fails</li></ul>
<p><a class="primary-link" href="playground.html">Open the firmware playground →</a></p>
</section>
</div>
<div class="connect"><b>How they connect.</b> The firmware playground's rectifier stage estimates its PFC inductor (FA10507: ≈ {pfc['l_uh']:.0f} µH at {pfc['i_pk']:.1f} A peak) <span class="miniarrow">→</span> one click sizes it in Magnetics against real cores <span class="miniarrow">→</span> with the closest past designs alongside. Same products, both initiatives.</div>
<div class="key">
<div><b>Real</b>IntelliPower product data sheets; Magnetics Inc. and Ferroxcube core data; the posting.</div>
<div><b>Synthetic</b>The legacy firmware corpus, the magnetics drawings, and their blind answer keys.</div>
<div><b>Assumed</b>Control board, design choices, inductor ripple, processor pairing. Tagged in the tools; listed in <a href="how.html#assumptions">How it works</a>.</div>
</div>
<p class="sub">Not claimed: power-electronics design, loop tuning, finished magnetics designs, EMI, or certification. Engineers own those; these tools carry and check their numbers.</p>
<details class="more-box" open><summary>The posting, my assumptions, and how I'd check them in week one</summary>
<figure class="posting"><div class="shot"><a href="assets/ametek_posting.jpg" target="_blank" rel="noopener"><img src="assets/ametek_posting.jpg" alt="Screenshot of the AI Automation Intern posting on AMETEK's careers site: about us, job summary with two initiatives (magnetics design automation; firmware modification and calibration automation), and key responsibilities" loading="lazy" width="1040" height="806"></a></div>
<figcaption>The posting on AMETEK's careers site, posted Oct 15, 2026, captured Oct 16, 2026 (<span class="mono">jobs.ametek.com/job/Orange-AI-Automation-Intern-CA-92865/1420689600</span>). Scroll inside the box, or click for full size.</figcaption></figure>
<p>The posting describes six problems: magnetics design iterations, hand-edited firmware constants, specs that aren't machine-usable, provable validation, undocumented process, and responsible AI adoption. This demo addresses the first two (magnetics: the data step and first-pass sizing; firmware constants: end to end) and supports the next four.</p>
<table><tr><th>#</th><th>Assumption</th><th>Why I think so</th><th>Confidence</th><th>How to check</th></tr>
<tr><td>A1</td><td>Calibration and config constants live in C source (#defines / const tables)</td><td>The posting says so</td><td>High</td><td>Read one product's source</td></tr>
<tr><td>A2</td><td>Many constants derive from data sheet ratings</td><td>Data sheet fields map cleanly to limits (1500 VA ÷ 120 V × 1.20 = 15 A)</td><td>Medium</td><td>Trace ten constants to their origin</td></tr>
<tr><td>A3</td><td>Alternate-component substitutions change sense gains</td><td>Engineering postings: "qualify new, or alternate components"</td><td>Medium</td><td>Ask how the last substitution was handled</td></tr>
<tr><td>A4</td><td>The processor is a TI C2000 part</td><td>Posting asks for TI chipsets; public site says DSP firmware</td><td>Medium</td><td>Look at a board</td></tr>
<tr><td>A5</td><td>Specs are not machine-readable today</td><td>All three data sheets checked contain an internal inconsistency</td><td>Medium</td><td>See the spec source of truth</td></tr>
<tr><td>A6</td><td>Some calibration is per unit at a test station</td><td>The phrase "calibration gains"</td><td>Low</td><td>Ask production test</td></tr>
<tr><td>A7</td><td>Past magnetics designs live in drawings and spreadsheets, not a database</td><td>The posting asks for a tool trained on "historical designs"</td><td>Medium</td><td>Ask for ten recent inductor drawings</td></tr>
</table></details>
<p class="cta" style="margin-top:28px"><a href="ai.html">AI practice</a><a href="audit.html">Legacy audit</a><a href="reports/index.html">Review reports</a><a href="backstory.html">Tim Otholt · backstory</a></p>
"""
    return _page("firmware-calgen: two AI automation initiatives", "index.html", body)


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
<h2>AI classification results</h2>
<p class="sub">Scored against the blind answer key; mean (min–max) over recorded runs. Bar set before any model ran: mean ≥ {BAR_CATEGORY:.0f}% category and ≥ {BAR_UNITS:.0f}% units. Recorded runs are replayed here; no model is called from this page.</p>
<table><tr><th>Model</th><th>Runs</th><th>Category</th><th>Units</th><th>Typed vs derived</th><th>Rule mapping</th><th>Cost / run</th><th>Verdict</th></tr>{''.join(ai_rows)}
</table>
<p class="sub">What this means: gpt-5.4-nano maps legacy constants to the right rule almost every time, which is what the audit needs, but its category labels disagree with the key on borderline cases (is a 4095 ADC count "sense full scale" or "other"?) often enough to miss the bar. Under the rule set in advance, no recorded model passes yet; the next step would be a stronger model, not a looser bar. History: an earlier single run scored 91% on category with a different rule set, and the very first run scored 39% because of two harness bugs (fixed and tested). All runs are kept in the repository.</p>
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
<h2>What a generated line looks like</h2>
<pre>{_e(GENERATED_SAMPLE)}</pre>
<p class="sub">The formula, every input, and the file each came from travel with the constant. The review report typesets the same derivation, and a test checks that the typeset math equals the computed value.</p>
<h2 id="assumptions">Assumptions this demo makes</h2>
<p class="sub">IntelliPower doesn't publish its firmware, board, or magnetics designs, so these are stated, not known. Values that rest on them are tagged <i>assumption</i> in the tools.</p>
{ASSUMPTIONS_HTML}
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


def page_magnetics(data: dict, key_match: tuple[int, int]) -> str:
    recs = data["records"]
    nflag = sum(r["flagged"] for r in recs)
    lim = data["limits"]
    core_rows = "".join(
        f"<tr><td class='mono'>{_e(c['name'])}</td><td>{_e(c['vendor'])} {_e(c['material'])} {_e(c['family'])}</td><td>{c['al_nh']:g} ± {c['al_tol_pct']:g}%</td>"
        f"<td>{c['ae_mm2']:g}</td><td>{c['le_mm']:g}</td><td>{c['wa_mm2']:g}{' *' if c['wa_basis'] != 'data sheet' else ''}</td>"
        f"<td>{'' if c['h80_oe'] is None else format(c['h80_oe'], 'g') + ' Oe'}{'' if c['bsat_mt'] is None else format(c['bsat_mt'], 'g') + ' mT'}</td><td class='sub'>{_e(c['source'])}</td></tr>"
        for c in data["cores"])
    body = f"""<h1>Magnetics</h1>
<p class="lead">The posting's first initiative is an AI tool that speeds up inductor and transformer design using past designs. That tool needs two things first, and this page demonstrates both: past drawings turned into structured, checked, searchable data, and a first-pass sizing tool that turns a requirement into checked starting designs from real cores. Neither replaces a magnetics engineer; they shorten the path to the first good prototype.</p>
<div class="proof">
<div><b>{len(recs)}</b><span>synthetic component drawings (PDF), read back from their text layer</span></div>
<div><b>{len(data['cores'])}</b><span>real cores, values transcribed from vendor data sheets with citations</span></div>
<div><b>{nflag} flagged</b><span>for review by physics checks; agrees with the blind answer key on {key_match[0]} of {key_match[1]} drawings</span></div>
</div>
<section class="sizer" id="size">
<h2>Size an inductor</h2>
<p class="sub">Enter a requirement; every Kool Mµ toroid in the catalog, stacked one to four high, is tried with the fewest turns that reach the inductance <i>at peak current</i>, the thinnest wire within the current-density limit, and a window-fill check. Computed in your browser by the same Python as the checks below. A first pass for an engineer to start from, not a finished design.</p>
<p class="sub" id="sz-from"></p>
<div class="msearch">
<label>Inductance at peak <input id="sz-l" type="number" min="0" step="any" value="330" placeholder="µH"></label>
<label>RMS current <input id="sz-irms" type="number" min="0" step="any" value="4" placeholder="A"></label>
<label>Peak current <input id="sz-ipk" type="number" min="0" step="any" value="4.5" placeholder="A"></label>
<label>Keep at peak <select id="sz-ret"><option value="0.8">≥ 80% (conservative)</option><option value="0.5">≥ 50% (common for PFC)</option></select></label>
<button id="sz-go" class="btn primary-btn" type="button">Size it</button>
</div>
<div id="sz-out" aria-live="polite"><p class="sub">Loading the in-browser engine…</p></div>
</section>
<h2>Past designs (synthetic drawings)</h2>
<div class="msearch">
<label>Kind <select id="f-kind"><option value="">All</option><option value="inductor">Inductors</option><option value="transformer">Transformers</option></select></label>
<label>Inductance from <input id="f-lmin" type="number" min="0" step="any" placeholder="µH"></label>
<label>to <input id="f-lmax" type="number" min="0" step="any" placeholder="µH"></label>
<label>Current at least <input id="f-imin" type="number" min="0" step="any" placeholder="A"></label>
<label>Status <select id="f-status"><option value="">All</option><option value="pass">Passed</option><option value="flag">Needs review</option></select></label>
<label class="grow">Search <input id="f-text" type="text" placeholder="drawing, title, core, material"></label>
<button id="f-reset" class="btn" type="button">Clear</button>
</div>
<p class="sub" id="m-count"></p>
<table class="mlist"><thead><tr><th>Drawing</th><th>Title</th><th>Core</th><th>Inductance</th><th>Current</th><th>Checks</th></tr></thead><tbody id="m-list"></tbody></table>
<div id="m-detail"></div>
<h2>How it works</h2>
<ol class="prose">
<li><b>Extract.</b> Each drawing's PDF text layer is parsed into fields (core, winding table, electrical table, title block). Every field keeps the text it came from. These drawings share one template; real drawings vary, so the first real step would be sampling about ten of yours to fix the schema, with a vision model and human review for scans.</li>
<li><b>Check.</b> Textbook physics against vendor data: stated inductance vs A<sub>L</sub>·N² (within the core's A<sub>L</sub> tolerance), DC bias on powder cores (peak magnetizing force vs the data sheet's 80%-permeability point), transformer peak flux vs B<sub>sat</sub>, turns ratio, current density, and window fill. Anything that fails goes to review with the reason and the math.</li>
<li><b>Search.</b> Filter checked records, and rank the closest past designs, the question a design engineer actually asks first.</li>
</ol>
<h2>Core catalog (real data)</h2>
<table><tr><th>Core</th><th>Type</th><th>A<sub>L</sub> (nH/T²)</th><th>A<sub>e</sub> (mm²)</th><th>l<sub>e</sub> (mm)</th><th>W<sub>a</sub> (mm²)</th><th>Limit</th><th>Source</th></tr>{core_rows}</table>
<p class="sub">Limit is the DC bias at 80% permeability for powder toroids, or minimum B<sub>sat</sub> at 100 °C for ferrite. * E-core window derived from nominal dimensions as (B − C)/2 × 2E, before the coil former.</p>
<h2>Assumptions and limits</h2>
<ul class="prose">
<li>Drawings, part numbers, and designs are <b>synthetic</b>; seeded mistakes are listed in a blind answer key the checks never read.</li>
<li>Design limits are textbook assumptions: current density ≤ {lim['j_max_a_per_mm2']:g} A/mm²; window fill ≤ {lim['fill_max_toroid'] * 100:.0f}% (toroids) or {lim['fill_max_ecore'] * 100:.0f}% (E cores, bare window); transformer flux ≤ {lim['bsat_margin'] * 100:.0f}% of B<sub>sat</sub>; turns ratio within {lim['ratio_tol_pct']:g}%.</li>
<li>First-order physics only: no core-loss, AC winding-loss, or thermal model yet. Those, and the design recommendations, are the next steps once real data exists, and they belong to your magnetics engineers.</li>
</ul>
<script id="mag-data" type="application/json">{_script_json(data)}</script>"""
    scripts = '<script src="assets/pyodide/pyodide.js"></script><script src="assets/magnetics.js?v=' + ASSET_VERSION + '"></script>'
    return _page("Magnetics", "magnetics.html", body, scripts=scripts)


def page_ai(ai: dict[str, float]) -> str:
    cost = f"${ai['cost']:.4f}" if ai.get("cost") else "under a cent"
    body = f"""<div class="story-page wide">
<h1>AI practice</h1>
<p class="lead">The posting asks for more than two tools: AI best practices across the organization, AI agents and productivity tools, and results presented to business and technical leaders. This page shows how I already work that way, and how I'd run it at IntelliPower.</p>

<section class="sblock thesis"><div class="slabel">1 · This demo was built with AI agents</div>
<p><b>Spec first.</b> A written plan (<span class="mono">docs/PLAN.md</span>) was approved before any code. Claude Code then built the tool in milestones over about a day of directed sessions, each step a small commit with its own tests. I chose the problem, approved the plan, and reviewed and redirected the work; the AI wrote most of the code.</p>
<p><b>Gates on AI output.</b> Every change passes the test suite before it ships: generated files must match a fresh generation, typeset math must equal the computed values, and the generated C must build and pass known-answer tests. One early commit went out with stale generated headers; the freshness test caught it, and since then every commit waits for the test run.</p>
<p><b>AI reviewing AI.</b> An AI reviewer, prompted to act as a power-electronics firmware lead, found a real physics error: the timed RMS overload was wired to the fast hardware comparator. A second review found five more issues (a 60 Hz-only input window on a 50/60 Hz unit, "fixed-point" code doing float math, an include-order hazard, stale corpus notes, overstated AI wording). All were fixed, and each code fix got a test so it can't come back.</p>
</section>

<section class="sblock why"><div class="slabel">2 · AI inside the tool, measured</div>
<p><b>Where it's used.</b> Drafting what each unexplained constant in legacy firmware is: its category, units, whether it's typed or derived, and which spec rule it corresponds to. A person reviews every draft. Generating firmware never calls a model.</p>
<p><b>Measured before trusted.</b> A blind answer key and a bar set before any model ran (≥ 90% category, ≥ 85% units). Over {ai.get('runs', 3):.0f} recorded runs, gpt-5.4-nano mapped constants to the right rule {ai['rule']:.0f}% of the time and got units right {ai['units']:.0f}% of the time, but category only {ai['category']:.0f}%: below the bar, reported as is. About {cost} per run. The very first run scored 39% because of two bugs in my harness, found by reading the raw responses before trusting the score.</p>
<p><b>Data sheets.</b> AI read the three data sheet PDFs and drafted the structured rows, each with its page citation. The consistency gate then flagged an inconsistency in every one of the three sheets. Details are on the <a href="audit.html">Audit</a> page.</p>
</section>

<section class="sblock back"><div class="slabel">3 · Proposed: a 90-day AI pilot plan</div>
<p>A proposal from the outside. The first month exists to replace my guesses with your data.</p>
<table class="plan"><tr><th>Days</th><th>Work</th><th>Result</th></tr>
<tr><td>1–30</td><td><b>Map.</b> Interview teams; list repetitive, document-heavy work with rough hours and risk. Classify data (public, proprietary, export-controlled or defense, vendor-confidential) and decide which models may touch which.</td><td>Workflow map, data rules, ranked pilot list</td></tr>
<tr><td>31–60</td><td><b>Pilot.</b> Run about three pilots, each with a success measure set before it starts and a person approving every output.</td><td>Measured results; each pilot kept or stopped</td></tr>
<tr><td>61–90</td><td><b>Scale or stop.</b> Turn what worked into documented tools with owners and training; write the AI best-practice guide.</td><td>Playbook and a results presentation</td></tr>
</table>
<p><b>Candidate pilots</b> (to confirm in the first month):</p>
<ul>
<li><b>Engineering:</b> firmware constants from specs (this demo); data sheet consistency checks; paperwork for qualifying alternate parts.</li>
<li><b>Operations:</b> summaries and trend flags from test reports; keeping specs and procedures in sync across versions.</li>
<li><b>Business:</b> first drafts of quotes and RFQ answers from the product catalog; searchable answers from internal documents.</li>
</ul>
<p><b>Guardrails:</b> classify data before choosing tools; defense, export-controlled, and vendor-confidential data only on approved or local models; a person reviews every AI output; every pilot is measured against a bar set in advance; costs are tracked.</p>
</section>
</div>"""
    return _page("AI practice", "ai.html", body)


def page_backstory(ai: dict[str, float]) -> str:
    body = f"""<div class="story-page">
<h1>Tim Otholt</h1>
<p class="lead">Who built this demo, why an internship, and the bet it makes about the problem.</p>
<div class="prose roomy">
<section class="sblock back"><div class="slabel">Backstory</div><p>I wrote C firmware and BIOS code at Phoenix Technologies, Quantum, AMD, and VM Labs, where constants had to be exactly right for each specific board. I've come back to engineering through an A.A.S. in AI software engineering, and this posting described a problem I recognized: numbers hand-edited in C source that should come from the spec. I built this demo to understand the problem as well as I could from the outside, and to show how I would approach it.</p></section>
<section class="sblock why"><div class="slabel">Why an internship</div><p>I wrote firmware and BIOS code from 1988 to 2001, then spent twenty years in film and live production. To rebuild my engineering career I went back to school: I completed Per Scholas's full-stack software engineering course in 2024 (3.8 GPA), and I'm now working toward an A.A.S. in AI Software Engineering (4.0 GPA) as the first step toward a B.S. An internship is the honest way back in. The fundamentals still apply: bringing up new boards, getting each board's constants exactly right, and debugging with scopes and emulators. But TI's C2000 parts, today's toolchains, and power electronics are new to me. I'd rather learn them inside a team that ships real products, while contributing the automation and AI tooling this role describes. The demo I built is a sample of how I'd work.</p></section>
<section class="sblock thesis"><div class="slabel">Thesis</div><p>IntelliPower publicly describes thousands of configure-to-order variants built from shared designs, and its engineering postings mention keeping legacy boards alive with alternate components. Every variant's ratings and every board's measurement chain must end up as correct constants in firmware; I assume much of that is done by hand today, from data sheets that aren't always consistent (all three I transcribed contain an inconsistency). The right tool makes that path deterministic, traceable, and gated. AI belongs only where the input is messy: here it drafts what each legacy constant is, and a person reviews every draft. Measured on a 33-constant synthetic set against a blind answer key, a low-cost model (gpt-5.4-nano) maps constants to the right rule {ai['rule']:.0f}% of the time but its category labels reach only {ai['category']:.0f}%, below the bar I set in advance, and I report that rather than move the bar. AI never writes firmware.</p></section>
</div>
</div>"""
    return _page("Tim Otholt: backstory and thesis", "backstory.html", body)


def page_playground(default: dict) -> str:
    opts = playground.options()
    body = f"""<h1>Playground</h1>
<p class="sub">Choose a product, change an input on the left, and watch every stage's firmware constants, gates, and generated C follow on the right. Computed in your browser by the same Python code as the command-line tool; nothing is uploaded.</p>
<div class="ptabs" id="products" role="tablist" aria-label="Product data sheet"></div>
<div id="engine" class="sub engine">Showing pre-computed results · loading the in-browser engine…</div>
<div class="statusbar"><div id="gates" class="pills"></div></div>
<div class="pg">
<section class="ins" aria-label="Inputs"><div class="colhead">Inputs · change anything</div><div id="inputs" class="inputs"></div><div id="probs"></div></section>
<section class="stages" aria-label="UPS power flow, top to bottom"><div class="colhead">Power flow · click a stage</div><div id="flow"></div></section>
<section class="fms"><div class="colhead" id="fhead">Formulas</div><div class="pills" id="tabs"></div><div id="formulas"></div></section>
</div>
<script id="default-data" type="application/json">{_script_json(default)}</script>
<script id="options" type="application/json">{_script_json(opts)}</script>"""
    scripts = '<script src="assets/pyodide/pyodide.js"></script><script src="assets/playground.js?v=' + ASSET_VERSION + '"></script>'
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
    import yaml

    from calgen.vendor import stage

    specs = root / "specs"
    rules = load_rules(specs / "rules.yaml")
    if out.exists():
        shutil.rmtree(out)
    assets = out / "assets"
    stage(vendor_cache, assets, download=download)
    js = Path(__file__).with_name("playground.js").read_text(encoding="utf-8")
    mjs = Path(__file__).with_name("magnetics.js").read_text(encoding="utf-8")
    engine = json.dumps(bundle(root))
    global ASSET_VERSION  # browsers and the Pages CDN cache assets; a new hash forces a fresh copy
    ASSET_VERSION = hashlib.sha256((SITE_CSS + js + mjs + engine).encode()).hexdigest()[:12]
    (assets / "site.css").write_text(SITE_CSS, encoding="utf-8")
    (assets / "playground.js").write_text(js, encoding="utf-8")
    (assets / "magnetics.js").write_text(mjs, encoding="utf-8")
    (assets / "calgen_bundle.json").write_text(engine, encoding="utf-8")
    corpus, cands, conf = audit_results(root, specs, rules)
    nano = [x[0] for x in model_runs(corpus, cands, rules).get("gpt-5.4-nano", [])]
    ai = {k: (sum(x.pct(getattr(x, k)) for x in nano) / len(nano) if nano else 0.0) for k in ("rule", "category", "units")}
    prices = yaml.safe_load((corpus / "ai_runs" / "prices.yaml").read_text()) if (corpus / "ai_runs" / "prices.yaml").exists() else {}
    p = prices.get("gpt-5.4-nano")
    ai["runs"] = float(len(nano))
    ai["cost"] = sum((x.input_tokens * p["input"] + x.output_tokens * p["output"]) / 1e6 for x in nano) / len(nano) if p and nano else 0.0
    shutil.copyfile(root / "docs" / "img" / "ametek_posting_2026-10-15.jpg", assets / "ametek_posting.jpg")
    (out / "reports").mkdir(parents=True, exist_ok=True)
    (out / "reports" / "index.html").write_text(page_reports(out, specs, rules), encoding="utf-8")
    (out / "audit.html").write_text(page_audit(root, specs, rules), encoding="utf-8")
    (out / "how.html").write_text(page_how(specs, rules), encoding="utf-8")
    (out / "backstory.html").write_text(page_backstory(ai), encoding="utf-8")
    (out / "ai.html").write_text(page_ai(ai), encoding="utf-8")
    from calgen import magnetics as mg

    mdata = mg.site_records(root)
    key = yaml.safe_load((root / "corpus" / "magnetics" / "ANSWER_KEY.yaml").read_text(encoding="utf-8"))
    agree = sum(sorted(c["id"] for c in r["checks"] if c["status"] == mg.FLAG) == sorted(key.get(r["id"], [])) for r in mdata["records"])
    (out / "magnetics").mkdir(exist_ok=True)
    import pypdfium2 as pdfium  # rasterize previews: embedded PDF viewers are unreliable across browsers

    for r in mdata["records"]:
        src = root / "corpus" / "magnetics" / "drawings" / f"{r['id']}.pdf"
        shutil.copyfile(src, out / "magnetics" / f"{r['id']}.pdf")
        pdf = pdfium.PdfDocument(str(src))
        pdf[0].render(scale=1.6).to_pil().convert("L").save(out / "magnetics" / f"{r['id']}.png", optimize=True)
        pdf.close()
    (out / "magnetics.html").write_text(page_magnetics(mdata, (agree, len(mdata["records"]))), encoding="utf-8")
    thumb_rec = next(r for r in mdata["records"] if r["id"] == "MAG-001")
    thumb = thumb_rec["figures"][0].split("<figcaption>")[0].replace('<figure class="mfig">', "")
    pfc = playground.run(specs)["inductors"]["rect"]
    mag = {"drawings": len(mdata["records"]), "cores": len(mdata["cores"]), "agree": agree, "thumb": thumb, "pfc": pfc}
    (out / "index.html").write_text(page_home(audit_counts(conf), ai, mag), encoding="utf-8")
    (out / "playground.html").write_text(page_playground(playground.run(specs)), encoding="utf-8")
    (out / ".nojekyll").write_text("", encoding="utf-8")
    shutil.copyfile(root / "LICENSE", out / "LICENSE.txt")
    shutil.copyfile(root / "THIRD_PARTY_NOTICES.md", out / "THIRD_PARTY_NOTICES.md")
    return out
