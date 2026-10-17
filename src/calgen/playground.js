/* Playground front end. All engineering math runs in Python (calgen.playground)
 * inside the browser via Pyodide; this file only renders its JSON.
 * Self-contained: every asset is loaded from this site. */
(function () {
  "use strict";
  var DATA = JSON.parse(document.getElementById("default-data").textContent);
  var OPTS = JSON.parse(document.getElementById("options").textContent);
  var state = { product: "FA10507", board: "A", target: "f28004x", edits: {}, sel: null, block: null, tab: "math" };
  var engine = null;
  var FLOW = {
    "in": ["vin_min", "vin_max", "iin_limit"],
    "rect": ["vbus_min"],
    "bus": ["vbus_set", "vbus_fs"],
    "inv": ["vout_set", "fout_mode", "pwm_period"],
    "out": ["iout_rated", "iout_trip", "iout_trip_dac_hi"],
    "batt": ["vbat_nom", "vbat_cutoff"]
  };
  var TAGNAME = { datasheet: "data sheet", derived: "derived", design: "design" };

  function $(id) { return document.getElementById(id); }
  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]; }); }
  function byId(id) { for (var i = 0; i < DATA.constants.length; i++) { if (DATA.constants[i].id === id) return DATA.constants[i]; } return null; }
  function tex(el) {
    if (!window.katex) return;
    el.querySelectorAll(".tex").forEach(function (t) {
      var d = document.createElement("div");
      try { katex.render(t.textContent, d, { displayMode: true, throwOnError: false }); t.parentNode.replaceChild(d, t); } catch (e) { /* keep text */ }
    });
  }
  function dot(status) { return status === "ok" ? "d-ok" : status === "fail" ? "d-bad" : "d-na"; }

  function renderProducts() {
    var html = "";
    Object.keys(OPTS.products).forEach(function (k) {
      var parts = OPTS.products[k].split(" · ");
      html += '<div class="it' + (k === state.product ? " sel" : "") + '" data-p="' + esc(k) + '" role="button" tabindex="0">' +
        '<span>' + esc(parts[0]) + '<br><span class="v" style="font-family:system-ui;font-size:11px">' + esc(parts.slice(1).join(" · ")) + "</span></span></div>";
    });
    $("products").innerHTML = '<div class="blk">Product (public data sheet)</div>' + html;
    $("products").querySelectorAll(".it").forEach(function (e) {
      var go = function () { if (!engine) return; state.product = e.dataset.p; state.edits = {}; recompute(); };
      e.onclick = go; e.onkeydown = function (ev) { if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); go(); } };
    });
  }

  function changed(id) { return (DATA.changed || []).indexOf(id) >= 0; }
  function shown(c) {
    if (!changed(c.id) || !DATA.baseline) return esc(c.display);
    return '<span class="was">' + esc(DATA.baseline[c.id]) + '</span> → <b>' + esc(c.display) + "</b>";
  }

  function flowBox(b) {
    var title = DATA.blocks[b];
    var rows = FLOW[b].map(function (id) {
      var c = byId(id); if (!c) return "";
      return '<div class="r' + (changed(id) ? " chg" : "") + '" title="' + esc(c.symbol) + '">' + shown(c) + '<span class="tag tag-' + c.tag + '">' + esc(TAGNAME[c.tag]) + "</span></div>";
    }).join("");
    var summary = DATA.summaries ? '<div class="sum">' + esc(DATA.summaries[b]) + "</div>" : "";
    var bad = DATA.constants.some(function (c) { return c.block === b && c.status === "fail"; }) ||
      DATA.checks.some(function (k) { return k.block === b && k.status === "fail"; });
    var any = DATA.constants.some(function (c) { return c.block === b && changed(c.id); });
    return '<div class="fb' + (state.block === b ? " sel" : "") + (bad ? " bad" : "") + (any ? " has-chg" : "") + '" data-b="' + b + '" role="button" tabindex="0"><div class="t">' + esc(title) + "</div>" + summary + rows + "</div>";
  }

  function renderFlow() {
    var arrow = '<div class="farrow" aria-hidden="true">→</div>';
    var main = ["in", "rect", "bus", "inv", "out"].map(flowBox).join(arrow);
    $("flow").innerHTML = '<div class="fgrid">' + main +
      '<div class="fvert" aria-hidden="true">↕</div><div class="under">' + flowBox("batt") + "</div></div>" +
      '<div class="sub" style="width:100%">Power flows left to right; the battery charges from and discharges into the DC bus. ' +
      'Click a block to filter the constants below. Highlighted values differ from the product as shipped (board rev A, F28004x-class, default design values).<br>' +
      esc(DATA.footnote || "") + "</div>";
    $("flow").querySelectorAll(".fb").forEach(function (e) {
      var go = function () { state.block = state.block === e.dataset.b ? null : e.dataset.b; state.sel = null; render(); };
      e.onclick = go; e.onkeydown = function (ev) { if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); go(); } };
    });
  }

  function renderInputs() {
    var owners = {};
    var dis = engine ? "" : " disabled";
    owners.Board = '<div class="inp"><label for="board">Control board revision</label><select id="board"' + dis + '><option value="A">rev A (original amplifier)</option><option value="B">rev B (alternate amplifier)</option></select></div>';
    owners.Chip = '<div class="inp"><label for="target">Target processor</label><select id="target"' + dis + '><option value="f28004x">F28004x-class (float32)</option><option value="f2803x">F2803x-class (IQ20, legacy)</option></select></div>';
    OPTS.editable.forEach(function (e) {
      var v = e.key in state.edits ? state.edits[e.key] : DATA.inputs[e.key];
      var unit = e.unit === "ratio" ? "V/V" : e.unit === "mohm" ? "mΩ" : e.unit;
      owners[e.owner] = (owners[e.owner] || "") + '<div class="inp"><label for="i-' + esc(e.key) + '">' + esc(e.label) + " (" + esc(unit) + ')</label><input type="number" step="any" min="0" id="i-' + esc(e.key) + '" data-k="' + esc(e.key) + '" value="' + esc(v) + '"' + dis + "></div>";
    });
    var order = [["Board", "hardware engineer"], ["Chip", "processor profile"], ["Design choice", "power engineer"]];
    $("inputs").innerHTML = order.map(function (o) {
      return '<div class="card"><h3>' + o[0] + " · " + o[1] + "</h3>" + (owners[o[0]] || "") + "</div>";
    }).join("") + '<div class="card"><h3>Product · data sheet</h3><p class="sub">Ratings are fixed by the public data sheet. Choose a product on the left.</p></div>';
    $("board").value = state.board; $("target").value = state.target;
    $("board").onchange = function () { state.board = this.value; recompute(); };
    $("target").onchange = function () { state.target = this.value; recompute(); };
    var timer = null;
    $("inputs").querySelectorAll("input[data-k]").forEach(function (inp) {
      inp.oninput = function () {
        var x = parseFloat(inp.value);
        if (!(x > 0)) { inp.setCustomValidity("Enter a positive number"); inp.reportValidity(); return; }
        inp.setCustomValidity("");
        state.edits[inp.dataset.k] = x;
        clearTimeout(timer); timer = setTimeout(recompute, 250);
      };
    });
  }

  function renderGates() {
    var nfail = DATA.constants.filter(function (c) { return c.status === "fail"; }).length;
    var kfail = DATA.checks.filter(function (k) { return k.status === "fail"; }).length;
    var stale = DATA.staleness.filter(function (s) { return s.status === "fail"; }).length;
    var dsb = DATA.datasheet.filter(function (d) { return d.status === "blocking"; }).length;
    var dsf = DATA.datasheet.length - dsb;
    var pills = [
      [nfail ? "bad" : "ok", "Constants " + (DATA.constants.length - nfail) + "/" + DATA.constants.length],
      [kfail ? "bad" : "ok", "Checks " + (kfail ? kfail + " failed" : "pass")],
      [dsb ? "bad" : dsf ? "warn" : "ok", "Data sheet " + (dsb ? "blocking" : dsf ? dsf + " for review" : "consistent")],
      [stale ? "bad" : "ok", "Staleness " + (stale ? stale + " stale" : "current")],
      [DATA.ok ? "ok" : "bad", DATA.ok ? "C generated" : "Nothing written (fail closed)"]
    ];
    var n = (DATA.changed || []).length;
    pills.push([n ? "chgpill" : "na", n ? n + " value" + (n === 1 ? "" : "s") + " changed vs shipped" : "matches shipped product"]);
    $("gates").innerHTML = pills.map(function (p) { return '<span class="pill ' + p[0] + '">' + esc(p[1]) + "</span>"; }).join("");
    var msgs = DATA.checks.filter(function (k) { return k.status === "fail"; }).map(function (k) { return k.message; })
      .concat(DATA.staleness.filter(function (s) { return s.status === "fail"; }).map(function (s) { return s.param + ": " + s.message; }))
      .concat(DATA.constants.filter(function (c) { return c.status === "fail"; }).map(function (c) { return c.symbol + ": " + c.message; }));
    $("failmsg").innerHTML = msgs.length ? '<ul style="color:var(--bad);font-size:13px">' + msgs.map(function (m) { return "<li>" + esc(m) + "</li>"; }).join("") + "</ul>" : "";
  }

  function visible() {
    return DATA.constants.filter(function (c) { return !state.block || c.block === state.block; });
  }

  function renderList() {
    var list = visible();
    if (!state.sel || !list.some(function (c) { return c.id === state.sel; })) {
      var bad = list.filter(function (c) { return c.status === "fail"; })[0];
      state.sel = (bad || list[0] || {}).id;
    }
    var html = "", last = null;
    list.forEach(function (c) {
      if (c.block !== last) { html += '<div class="blk">' + esc(DATA.blocks[c.block]) + "</div>"; last = c.block; }
      html += '<div class="it' + (c.id === state.sel ? " sel" : "") + '" data-id="' + esc(c.id) + '" role="button" tabindex="0" aria-pressed="' + (c.id === state.sel) + '">' +
        "<span>" + esc(c.symbol) + '</span><span style="display:flex;gap:6px;align-items:center"><span class="v' + (changed(c.id) ? " chg" : "") + '">' + shown(c) + '</span><span class="dot ' + dot(c.status) + '"></span></span></div>';
    });
    $("clist").innerHTML = html;
    $("clist").querySelectorAll(".it").forEach(function (e) {
      var go = function () { state.sel = e.dataset.id; renderList(); renderDetail(); };
      e.onclick = go; e.onkeydown = function (ev) { if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); go(); } };
    });
  }

  function renderDetail() {
    var tabs = [["math", "Derivation"], ["c", "Generated C"], ["diff", "Diff vs unedited"]];
    $("tabs").innerHTML = tabs.map(function (t) { return '<span class="pill tab' + (state.tab === t[0] ? " on" : "") + '" data-t="' + t[0] + '" role="button" tabindex="0">' + t[1] + "</span>"; }).join("");
    $("tabs").querySelectorAll(".tab").forEach(function (e) { e.onclick = function () { state.tab = e.dataset.t; renderDetail(); }; });
    var c = byId(state.sel), out = "";
    if (state.tab === "math" && c) {
      out = '<h3 class="mono" style="margin:4px 0">' + esc(c.symbol) + '</h3><p class="sub">' + esc(c.describe) + ' <span class="tag tag-' + c.tag + '">' + esc(TAGNAME[c.tag]) + "</span></p>" +
        (c.message ? '<p class="pill ' + (c.status === "fail" ? "bad" : "na") + '" style="display:inline-block">' + esc(c.message) + "</p>" : "") +
        c.latex.map(function (l) { return '<div class="eq"><div class="tex">' + esc(l) + "</div></div>"; }).join("") +
        (c.sources.length ? "<table><tr><th>Input</th><th>From</th><th>Data sheet text / note</th></tr>" + c.sources.map(function (s) {
          return "<tr><td class='mono'>" + esc(s.name) + "</td><td>" + esc(s.origin) + "</td><td>" + esc(s.quote) + "</td></tr>"; }).join("") + "</table>" : "");
      var checks = DATA.checks.filter(function (k) { return k.block === c.block; });
      if (checks.length) {
        out += '<h3 style="font-size:13px;margin-top:16px">Checks on this block</h3>' + checks.map(function (k) {
          return '<p class="sub"><span class="pill ' + (k.status === "ok" ? "ok" : k.status === "fail" ? "bad" : "na") + '">' + esc(k.id) + "</span> " + esc(k.describe) + "</p>" +
            k.latex.map(function (l) { return '<div class="eq"><div class="tex">' + esc(l) + "</div></div>"; }).join(""); }).join("");
      }
    } else if (state.tab === "c") {
      out = DATA.header ? '<p><a class="btn" id="dl" href="#">Download calgen_' + esc(DATA.variant) + '.h</a></p><pre>' + esc(DATA.header) + "</pre>"
        : '<p class="pill bad" style="display:inline-block">Not generated: ' + esc(DATA.gate_message) + "</p>";
    } else if (state.tab === "diff") {
      out = DATA.diff ? "<pre>" + DATA.diff.split("\n").map(function (l) {
        var cls = l[0] === "+" && l.slice(0, 3) !== "+++" ? "add" : l[0] === "-" && l.slice(0, 3) !== "---" ? "del" : "";
        return '<span class="' + cls + '">' + esc(l) + "</span>"; }).join("\n") + "</pre>"
        : '<p class="sub">' + (Object.keys(state.edits).length ? "No difference, or nothing generated." : "Edit a board or design value to see what changes in the generated C.") + "</p>";
    }
    $("cdetail").innerHTML = out;
    tex($("cdetail"));
    var dl = $("dl");
    if (dl) dl.onclick = function (ev) {
      ev.preventDefault();
      var a = document.createElement("a");
      a.href = URL.createObjectURL(new Blob([DATA.header], { type: "text/x-c" }));
      a.download = "calgen_" + DATA.variant + ".h"; a.click(); URL.revokeObjectURL(a.href);
    };
  }

  function render() { renderProducts(); renderFlow(); renderInputs(); renderGates(); renderList(); renderDetail(); }

  function recompute() {
    if (!engine) return;
    $("engine").textContent = "Computing…";
    try {
      var req = JSON.stringify({ product: state.product, board: state.board, target: state.target, edits: state.edits });
      DATA = JSON.parse(engine.run_json("/calgen/specs", req));
      if (!DATA.ok) { state.sel = null; state.block = null; }  // jump to the first failure
      $("engine").textContent = "Live: computed in your browser by calgen " + (DATA.ok ? "· all gates pass" : "· gates failed, nothing written");
    } catch (e) {
      $("engine").textContent = "Engine error: " + e.message;
    }
    render();
  }

  async function boot() {
    render();
    if (typeof loadPyodide !== "function") { $("engine").textContent = "In-browser engine unavailable; showing pre-computed results."; return; }
    try {
      var py = await loadPyodide({ indexURL: new URL("assets/pyodide/", location.href).href });
      await py.loadPackage(new URL("assets/pyodide/pyyaml-6.0.2-cp312-cp312-pyodide_2024_0_wasm32.whl", location.href).href);
      var files = await (await fetch("assets/calgen_bundle.json")).json();
      Object.keys(files).forEach(function (p) {
        var full = "/calgen/" + p, dir = full.slice(0, full.lastIndexOf("/"));
        py.FS.mkdirTree(dir); py.FS.writeFile(full, files[p]);
      });
      py.runPython("import sys; sys.path.insert(0, '/calgen/src')");
      engine = py.pyimport("calgen.playground");
      $("engine").textContent = "Live: the in-browser engine is ready. Change an input.";
      render();
    } catch (e) {
      $("engine").textContent = "In-browser engine failed to load (" + e.message + "); showing pre-computed results.";
    }
  }
  boot();
})();
