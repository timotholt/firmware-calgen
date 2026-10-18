/* Magnetics page (plain JavaScript). All numbers and verdicts come from the Python build
 * (calgen.magnetics.site_records); this file only filters and draws them. */
(function () {
  "use strict";
  var DATA = JSON.parse(document.getElementById("mag-data").textContent);
  var byId = {};
  DATA.records.forEach(function (r) { byId[r.id] = r; });
  var sel = DATA.records[0].id;

  function $(id) { return document.getElementById(id); }
  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]; }); }
  function num(id) { var v = parseFloat($(id).value); return isNaN(v) ? null : v; }
  function fmtL(uh) { return uh >= 1000 ? (uh / 1000).toPrecision(3) + " mH" : uh.toPrecision(3) + " µH"; }
  var FAIL_TEXT = { inductance: "stated inductance doesn't match Aₗ × N² within tolerance", core_known: "core not in the catalog",
    ratio: "turns ratio doesn't match the winding table", current_density: "wire too thin for the current", window_fill: "winding doesn't fit the window",
    dc_bias: "peak current drives the core past its rated permeability point", magnetizing: "minimum magnetizing inductance not met", flux: "peak flux above the limit" };
  function tex(el) {
    if (!window.katex) return;
    el.querySelectorAll(".tex").forEach(function (t) {
      var d = document.createElement("div");
      try { katex.render(t.textContent, d, { displayMode: true, throwOnError: false }); t.parentNode.replaceChild(d, t); } catch (e) { /* keep text */ }
    });
  }

  function matches(r) {
    var kind = $("f-kind").value, st = $("f-status").value, q = $("f-text").value.trim().toLowerCase();
    var lmin = num("f-lmin"), lmax = num("f-lmax"), imin = num("f-imin");
    if (kind && r.kind !== kind) return false;
    if (st === "pass" && r.flagged) return false;
    if (st === "flag" && !r.flagged) return false;
    if (lmin !== null && r.l_uh < lmin) return false;
    if (lmax !== null && r.l_uh > lmax) return false;
    if (imin !== null && r.i_a < imin) return false;
    if (q && (r.id + " " + r.title + " " + r.core + " " + r.material).toLowerCase().replace(/µ/g, "u").indexOf(q.replace(/µ/g, "u")) < 0) return false;
    return true;
  }

  function renderList() {
    var rows = DATA.records.filter(matches);
    $("m-count").textContent = rows.length + " of " + DATA.records.length + " drawings";
    $("m-list").innerHTML = rows.map(function (r) {
      return '<tr class="mrow' + (r.id === sel ? " on" : "") + '" data-id="' + esc(r.id) + '" tabindex="0"><td class="mono">' + esc(r.id) + "</td><td>" + esc(r.title) +
        '</td><td class="mono">' + esc(r.core) + "</td><td>" + esc(r.l_text) + (r.kind === "transformer" ? " min" : "") + "</td><td>" + r.i_a + " A RMS</td><td>" +
        (r.flagged ? '<span class="pill bad">review</span>' : '<span class="pill ok">pass</span>') + "</td></tr>";
    }).join("") || '<tr><td colspan="6" class="sub">No drawings match these filters.</td></tr>';
    $("m-list").querySelectorAll(".mrow").forEach(function (tr) {
      tr.onclick = function () { sel = tr.dataset.id; tab = null; render(); };
      tr.onkeydown = function (ev) { if (ev.key === "Enter") { sel = tr.dataset.id; tab = null; render(); } };
    });
  }

  // ---- record detail: design on the left, evidence tabs on the right ---------------------
  var tab = null; // current evidence tab; reset to the record's default when the selection changes
  var TABS = [["curve", "Curve"], ["flux", "Flux"], ["winding", "Winding"], ["drawing", "Drawing"]];
  function tabsHtml(avail, cur, attr) {
    return '<div class="etabs" role="tablist">' + TABS.filter(function (t) { return avail[t[0]]; }).map(function (t) {
      return '<button type="button" role="tab" class="etab' + (t[0] === cur ? " on" : "") + '" aria-selected="' + (t[0] === cur) + '" ' + attr + '="' + t[0] + '">' + t[1] + "</button>";
    }).join("") + "</div>";
  }
  function evidence(r, cur) {
    if (cur === "drawing") {
      return '<a href="magnetics/' + esc(r.id) + '.pdf" target="_blank" rel="noopener" title="Open the PDF"><img class="mpng" src="magnetics/' + esc(r.id) +
        '.png" alt="Drawing ' + esc(r.id) + ": " + esc(r.title) + '" width="1268" height="980"></a><p class="sub"><a href="magnetics/' + esc(r.id) +
        '.pdf" target="_blank" rel="noopener">Open the PDF</a> · synthetic drawing; the fields on the left were read from its text layer</p>';
    }
    return r.fig[cur] || '<p class="sub">Not available for this design.</p>';
  }
  function renderDetail() {
    var r = byId[sel];
    var avail = { curve: !!r.fig.curve, flux: !!r.fig.flux, winding: !!r.fig.winding, drawing: true };
    if (!tab || !avail[tab]) tab = r.default_tab;
    var fields = [["Drawing", r.id + " rev " + r.rev, "id"], ["Title", r.title, "title"], ["Core", r.core + " (" + r.core_desc + ")", "core"]];
    if (r.kind === "inductor") {
      fields.push(["Inductance (0 A)", r.l_text, "l_text"], ["Tolerance", "±" + r.l_tol_pct + "%", "l_tol_pct"], ["Peak current", r.i_pk_a + " A", "i_pk_a"]);
    } else {
      fields.push(["Magnetizing inductance (min)", r.l_text, "lm_text"], ["Primary drive", r.v_pri + " V square, " + r.f_khz + " kHz", "v_pri"], ["Turns ratio", r.source.ratio_text || "", "ratio_text"]);
    }
    r.windings.forEach(function (w) {
      fields.push(["Winding " + w.name, w.turns + " turns, " + w.strands + " × " + w.awg + " AWG, " + w.i_rms_a + " A RMS", w.name]);
    });
    var bad = r.checks.filter(function (c) { return c.status === "flag"; });
    var ran = r.checks.filter(function (c) { return c.status !== "n/a"; }).length, nm = r.checks.length - ran;
    var verdict = bad.length
      ? '<p class="verdict bad"><b>Needs review:</b> ' + bad.map(function (c) { return esc(FAIL_TEXT[c.id] || c.title); }).join("; ") + ". The evidence opens to show why.</p>"
      : '<p class="verdict ok"><b>Passes ' + ran + " modeled checks" + (nm ? "</b> (" + nm + " not modelled, listed below)." : ".</b>") + "</p>";
    var left = "<h3>" + esc(r.id) + " · " + esc(r.title) + "</h3>" + verdict + '<p class="sub">' + esc(r.scope) + "</p>" +
      '<details class="mag-extracted"><summary>Extracted fields and PDF sources</summary><div class="mag-table-scroll"><table class="mfields"><tr><th>Field</th><th>Value</th><th>Text it came from</th></tr>' +
      fields.map(function (f) { return "<tr><td>" + esc(f[0]) + "</td><td>" + esc(f[1]) + '</td><td class="mono sub">' + esc(r.source[f[2]] || "") + "</td></tr>"; }).join("") + "</table></div></details>" +
      "<h4>Physics checks</h4>" + r.checks.map(function (c) {
        var cls = c.status === "pass" ? "ok" : c.status === "flag" ? "bad" : "na";
        return '<details class="mcheck"' + (c.status === "flag" ? " open" : "") + '><summary><span class="pill ' + cls + '">' + esc(c.status === "flag" ? "review" : c.status) +
          "</span> <b>" + esc(c.title) + '</b> <span class="sub">' + esc(c.message) + "</span></summary>" +
          c.latex.map(function (l) { return '<div class="eq"><div class="tex">' + esc(l) + "</div></div>"; }).join("") + "</details>";
      }).join("") +
      '<h4>Closest past designs</h4><ul class="msim">' + r.similar.map(function (s) {
        var o = byId[s.id];
        return '<li><a href="#" data-id="' + esc(s.id) + '">' + esc(s.id) + "</a> " + esc(o.title) + " · " + esc(o.l_text) + ", " + o.i_a + " A" + (o.flagged ? ' <span class="pill bad">review</span>' : "") + "</li>";
      }).join("") + "</ul>";
    var right = tabsHtml(avail, tab, "data-tab") + '<div class="epanel">' + evidence(r, tab) + "</div>";
    $("m-detail").innerHTML = '<div class="m2col"><div class="mleft">' + left + '</div><aside class="mright" aria-label="Evidence">' + right + "</aside></div>";
    $("m-detail").querySelectorAll(".msim a").forEach(function (a) { a.onclick = function (ev) { ev.preventDefault(); sel = a.dataset.id; tab = null; render(); }; });
    $("m-detail").querySelectorAll(".etab").forEach(function (b) { b.onclick = function () { tab = b.dataset.tab; renderDetail(); }; });
    tex($("m-detail"));
  }

  // ---- sizing (runs calgen.magnetics in Pyodide) ----------------------------------------
  var engine = null, open = 0, lastReq = null, sztab = "curve", application = "dc_bias";
  function sizeNow() {
    if (!engine) return;
    var req = { l_uh: num("sz-l"), i_rms: num("sz-irms"), i_pk: num("sz-ipk"), min_retained: parseFloat($("sz-ret").value), application: application,
      past: DATA.records.filter(function (r) { return !r.flagged; }).map(function (r) { return { id: r.id, kind: r.kind, l_uh: r.l_uh, i_a: r.i_a }; }) };
    if (!(req.l_uh > 0 && req.i_rms > 0 && req.i_pk > 0)) { $("sz-out").innerHTML = '<p class="alert bad">Enter a positive inductance, RMS current, and peak current.</p>'; return; }
    if (req.i_pk < req.i_rms) { $("sz-out").innerHTML = '<p class="alert bad" role="alert">Peak current must be at least the RMS current.</p>'; return; }
    lastReq = req; open = 0; sztab = "curve";
    try {
      var res = JSON.parse(engine.size_json("/calgen/specs", JSON.stringify(req)));
      renderSizing(res);
    } catch (e) {
      $("sz-out").innerHTML = '<p class="alert bad" role="alert">Unable to size: ' + esc(e.message) + '</p>';
    }
  }
  function renderSizing(res) {
    var c = res.candidates, h = '<p class="sub"><b>' + esc(res.scope.verdict) + '</b><br>' + esc(res.scope.remaining) + '</p><details class="sub"><summary>Curve basis</summary><p>' + esc(res.scope.curve) + '</p></details>';
    if (res.error) {
      $("sz-out").innerHTML = '<p class="alert bad" role="alert">' + esc(res.error) + '</p>';
      return;
    }
    if (!c.length) {
      h += '<p class="alert bad">No candidate found within this catalog and the screening assumptions, even stacked four high. Review a larger core family or the design requirements.</p>';
    } else {
      h += '<p class="sub">' + c.length + " screening candidate" + (c.length === 1 ? "" : "s") + ", smallest core volume first. Select a row for its curve, winding, and calculations.</p>";
      if (c.some(function (x) { return x.retained < 0.8; })) h += '<p class="alert na">Candidates marked <span class="pill na">below 80%</span> keep less than 80% of their inductance at peak current. That is common for PFC inductors, but a drawing of one would be flagged by the drawing check below, which requires 80%.</p>';
      h += '<div class="mag-compare"><div class="mag-table-scroll" tabindex="0" role="region" aria-label="Candidate comparison"><table class="szt"><tr><th>Core</th><th>Stack · core height</th><th>Turns</th><th>Wire</th><th>L at 0 A (min A<sub>L</sub>)</th><th>L at peak (est.)</th><th>L kept at peak</th><th>J (RMS)</th><th>Fill</th><th>Core volume</th></tr>' +
        c.map(function (x, i) {
          var row = '<tr class="cand' + (open === i ? " on" : "") + '" data-i="' + i + '" tabindex="0"><td class="mono">' + esc(x.core) + "</td><td>×" + x.stack + " · " + x.height_mm.toFixed(0) + " mm</td><td>" + x.turns + "</td><td>" + x.strands + " × " + x.awg + " AWG</td><td>" +
            fmtL(x.l0_uh) + "</td><td><b>" + fmtL(x.l_pk_uh) + "</b></td><td>" + Math.round(x.retained * 100) + "%" + (x.retained < 0.8 ? ' <span class="pill na">below 80%</span>' : "") + "</td><td>" + x.j.toFixed(2) + " A/mm²</td><td>" + Math.round(x.fill * 100) + "%</td><td>" + (x.core_volume_mm3 / 1000).toFixed(1) + " cm³</td></tr>";
          return row;
        }).join("") + "</table></div></div>";
      var x = c[open] || c[0];
      h += '<div class="m2col szdetail"><div class="mleft"><h4>Selected design · ' + esc(x.core) + (x.stack > 1 ? " ×" + x.stack + " stacked" : "") + ": " + x.turns + " turns of " + x.strands + " × " + x.awg + " AWG</h4>" +
        '<div class="metric-strip"><div><small>L at peak · estimate</small><strong>' + fmtL(x.l_pk_uh) + '</strong></div><div><small>Inductance retained</small><strong>' + Math.round(x.retained * 100) + '%</strong></div><div><small>Window fill</small><strong>' + Math.round(x.fill * 100) + '%</strong></div></div><details class="mag-math"><summary>Derivations and checks</summary>' +
        x.latex.map(function (l) { return '<div class="eq"><div class="tex">' + esc(l) + "</div></div>"; }).join("") + "</details></div>" +
        '<aside class="mright" aria-label="Evidence">' + tabsHtml({ curve: true, winding: true }, sztab, "data-sztab") + '<div class="epanel">' + x.fig[sztab] + "</div></aside></div>";
    }
    if (res.rejected.length) {
      h += '<details><summary class="sub">' + (res.rejected.length === 1 ? "Why the other core doesn't work" : "Why the other " + res.rejected.length + " cores don't work") + "</summary><ul>" +
        res.rejected.map(function (r) { return '<li><span class="mono">' + esc(r.core) + "</span>: " + esc(r.reason) + "</li>"; }).join("") + "</ul></details>";
    }
    if (res.past.length) {
      h += '<p class="sub">Closest past designs (passed their checks): ' + res.past.map(function (p) { var o = byId[p.id]; return '<a href="#" data-id="' + esc(p.id) + '">' + esc(p.id) + "</a> " + esc(o.l_text) + ", " + o.i_a + " A"; }).join(" · ") + "</p>";
    }
    $("sz-out").innerHTML = h;
    $("sz-out").querySelectorAll("tr.cand").forEach(function (tr) {
      tr.onclick = function () { open = +tr.dataset.i; renderSizing(res); };
      tr.onkeydown = function (ev) { if (ev.key === "Enter") { open = +tr.dataset.i; renderSizing(res); } };
    });
    $("sz-out").querySelectorAll(".etab").forEach(function (b) { b.onclick = function () { sztab = b.dataset.sztab; renderSizing(res); }; });
    $("sz-out").querySelectorAll("a[data-id]").forEach(function (a) { a.onclick = function (ev) { ev.preventDefault(); sel = a.dataset.id; render(); $("m-detail").scrollIntoView({ behavior: "smooth" }); }; });
    tex($("sz-out"));
  }
  function fromHash() { // magnetics.html#size?name=...&l=...&irms=...&ipk=...&ret=...&from=...
    var m = location.hash.match(/^#size\?(.*)$/); if (!m) return false;
    var q = {}; m[1].split("&").forEach(function (kv) { var p = kv.split("="); q[p[0]] = decodeURIComponent(p[1] || ""); });
    if (q.l) $("sz-l").value = q.l; if (q.irms) $("sz-irms").value = q.irms; if (q.ipk) $("sz-ipk").value = q.ipk;
    if (q.ret) $("sz-ret").value = q.ret;
    application = q.application || "dc_bias";
    if (q.name) $("sz-from").innerHTML = "Requirement from the firmware playground: <b>" + esc(q.name) + "</b>" + (q.from ? " for " + esc(q.from) : "") + (q.basis ? ' <span title="' + esc(q.basis) + '">(first-pass estimate; hover for the basis)</span>' : "");
    return true;
  }
  async function boot() {
    var linked = fromHash();
    if (linked) $("size").scrollIntoView();
    if (typeof loadPyodide !== "function") { $("sz-out").innerHTML = '<p class="sub">In-browser engine unavailable.</p>'; return; }
    try {
      var py = await loadPyodide({ indexURL: new URL("assets/pyodide/", location.href).href });
      await py.loadPackage(new URL("assets/pyodide/pyyaml-6.0.2-cp312-cp312-pyodide_2024_0_wasm32.whl", location.href).href);
      var ver = (document.querySelector('script[src*="magnetics.js"]') || {}).src || "";
      var files = await (await fetch("assets/calgen_bundle.json" + (ver.indexOf("?") >= 0 ? ver.slice(ver.indexOf("?")) : ""))).json();
      Object.keys(files).forEach(function (p) { var full = "/calgen/" + p, dir = full.slice(0, full.lastIndexOf("/")); py.FS.mkdirTree(dir); py.FS.writeFile(full, files[p]); });
      py.runPython("import sys; sys.path.insert(0, '/calgen/src')");
      engine = py.pyimport("calgen.magnetics");
      sizeNow();
    } catch (e) {
      $("sz-out").innerHTML = '<p class="alert bad">In-browser engine failed to load: ' + esc(e.message) + "</p>";
    }
  }
  $("sz-go").onclick = sizeNow;
  ["sz-l", "sz-irms", "sz-ipk"].forEach(function (id) { $(id).onkeydown = function (ev) { if (ev.key === "Enter") sizeNow(); }; });
  $("sz-ret").onchange = sizeNow;
  window.addEventListener("hashchange", function () { if (fromHash()) { $("size").scrollIntoView(); sizeNow(); } });

  function render() { renderList(); renderDetail(); }
  ["f-kind", "f-status", "f-text", "f-lmin", "f-lmax", "f-imin"].forEach(function (id) { $(id).oninput = renderList; $(id).onchange = renderList; });
  $("f-reset").onclick = function () { ["f-text", "f-lmin", "f-lmax", "f-imin"].forEach(function (id) { $(id).value = ""; }); $("f-kind").value = ""; $("f-status").value = ""; renderList(); };
  render();
  boot();
})();
