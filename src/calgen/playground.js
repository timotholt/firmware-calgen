/* Playground front end (plain JavaScript, no framework, no build step).
 * All engineering math runs in Python (calgen.playground) inside the browser
 * via Pyodide; this file only renders its JSON. Every asset is served by this
 * site; nothing is uploaded. */
(function () {
  "use strict";
  var DATA = JSON.parse(document.getElementById("default-data").textContent);
  var OPTS = JSON.parse(document.getElementById("options").textContent);
  var state = { product: "FA10507", board: "A", target: "f28004x", edits: {}, stage: "out", open: {}, tab: "c" };
  var engine = null;
  var prev = null; // id -> display from the previous computation, for flashing what just changed
  var showReasons = true; // reasons appear only after the user pauses (red borders appear at once)
  var dismissed = {}; // stage -> true when its popover was closed; reset on the next change
  var reasonTimer = null;
  function revealReasonsAfter(ms) {
    showReasons = false; dismissed = {};
    clearTimeout(reasonTimer);
    reasonTimer = setTimeout(function () { showReasons = true; renderFlow(); renderGates(); }, ms);
  }
  var FLOW = {
    "in": ["vin_min", "vin_max", "iin_limit"],
    "rect": ["vbus_min"],
    "bus": ["vbus_set", "vbus_fs"],
    "inv": ["vout_set", "fout_mode", "pwm_period"],
    "out": ["iout_rated", "iout_trip", "iout_pk_limit", "iout_fs_pk", "iout_pklim_dac_hi"],
    "batt": ["vbat_nom", "vbat_cutoff"]
  };
  var TAGNAME = { datasheet: "data sheet", derived: "derived", assumption: "assumption", design: "design", override: "what-if" };

  function $(id) { return document.getElementById(id); }
  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]; }); }
  function byId(id) { for (var i = 0; i < DATA.constants.length; i++) { if (DATA.constants[i].id === id) return DATA.constants[i]; } return null; }
  function keyed(el, fn) { el.onclick = fn; el.onkeydown = function (ev) { if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); fn(); } }; }
  function tex(el) {
    if (!window.katex) return;
    el.querySelectorAll(".tex").forEach(function (t) {
      var d = document.createElement("div");
      try { katex.render(t.textContent, d, { displayMode: true, throwOnError: false }); t.parentNode.replaceChild(d, t); } catch (e) { /* keep text */ }
    });
  }
  function dot(status) { return status === "ok" ? "d-ok" : status === "fail" ? "d-bad" : "d-na"; }
  function changed(id) { return (DATA.changed || []).indexOf(id) >= 0; }
  function shown(c) {
    if (!changed(c.id) || !DATA.baseline) return esc(c.display);
    return '<span class="was">' + esc(DATA.baseline[c.id]) + "</span> → <b>" + esc(c.display) + "</b>";
  }
  function problems(b) {
    var out = DATA.constants.filter(function (c) { return c.block === b && c.status === "fail"; }).map(function (c) { return c.symbol + ": " + c.message; });
    out = out.concat(DATA.checks.filter(function (k) { return k.block === b && k.status === "fail"; }).map(function (k) { return k.message; }));
    if (b === "inv") out = out.concat(DATA.staleness.filter(function (x) { return x.status === "fail"; }).map(function (x) { return x.param + ": " + x.message; }));
    return out;
  }
  function allProblems() {
    var n = 0;
    Object.keys(FLOW).forEach(function (b) { n += problems(b).length; });
    return n; // staleness problems are counted under the inverter stage
  }
  function stageBad(b) {
    return DATA.constants.some(function (c) { return c.block === b && c.status === "fail"; }) ||
      DATA.checks.some(function (k) { return k.block === b && k.status === "fail"; });
  }

  // ---- product tabs ------------------------------------------------------
  function renderTabs() {
    $("products").innerHTML = Object.keys(OPTS.products).map(function (k) {
      var parts = OPTS.products[k].split(" · ");
      var on = k === state.product;
      return '<div class="ptab' + (on ? " on" : "") + '" role="tab" aria-selected="' + on + '" tabindex="0" data-p="' + esc(k) + '"><b>' + esc(parts[0]) + "</b>" + esc(parts.slice(1).join(" · ")) + "</div>";
    }).join("");
    $("products").querySelectorAll(".ptab").forEach(function (e) {
      keyed(e, function () { if (!engine || e.dataset.p === state.product) return; state.product = e.dataset.p; state.edits = {}; state.open = {}; revealReasonsAfter(300); recompute(); });
    });
  }

  // ---- vertical power flow -----------------------------------------------
  function stageBox(b) {
    var rows = FLOW[b].map(function (id) {
      var c = byId(id); if (!c) return "";
      return '<div class="r' + (changed(id) ? " chg" : "") + '" data-vid="' + esc(id) + '" title="' + esc(c.symbol) + '">' + shown(c) + '<span class="tag tag-' + c.tag + '">' + esc(TAGNAME[c.tag]) + "</span></div>";
    }).join("");
    var summary = DATA.summaries ? '<div class="sum">' + esc(DATA.summaries[b]) + "</div>" : "";
    if (b === "out" && DATA.summaries && DATA.summaries.sense) {
      var sat = DATA.summaries.sense.indexOf("SATURATES") >= 0;
      summary += '<div class="sense' + (sat ? " bad" : "") + '">' + esc(DATA.summaries.sense) + "</div>";
    }
    var any = DATA.constants.some(function (c) { return c.block === b && changed(c.id); });
    var probs = problems(b);
    var probHtml = probs.length && showReasons && !dismissed[b]
      ? '<div class="probs" role="alert"><button type="button" class="probx" data-x="' + b + '" aria-label="Dismiss">×</button><ul>' +
        probs.map(function (m) { return "<li>" + esc(m) + "</li>"; }).join("") + "</ul></div>" : "";
    return '<div class="fb' + (state.stage === b ? " sel" : "") + (stageBad(b) ? " bad" : "") + (any ? " has-chg" : "") +
      '" data-b="' + b + '" id="stage-' + b + '" role="button" tabindex="0" aria-pressed="' + (state.stage === b) + '"><div class="t">' + esc(DATA.blocks[b]) + "</div>" + summary + rows + probHtml + "</div>";
  }

  function renderFlow() {
    var down = '<div class="vdown" aria-hidden="true">↓</div>';
    $("flow").innerHTML = stageBox("in") + down + stageBox("rect") + down +
      '<div class="busrow">' + stageBox("bus") + '<div class="side" aria-hidden="true">↔</div>' + stageBox("batt") + "</div>" +
      down + stageBox("inv") + down + stageBox("out") +
      '<p class="sub" style="margin-top:10px">Highlighted values differ from the product as shipped (board rev A, F28004x-class, default design values). ' + esc(DATA.footnote || "") + "</p>" +
      '<p class="sub"><span class="tag tag-datasheet">data sheet</span> public rating · <span class="tag tag-derived">derived</span> from data sheet and public chip facts only · <span class="tag tag-assumption">assumption</span> uses an invented board part, margin, or generic chemistry figure · <span class="tag tag-design">design</span> engineer-supplied · <span class="tag tag-override">what-if</span> your override</p>';
    $("flow").querySelectorAll(".fb").forEach(function (e) {
      keyed(e, function () { state.stage = e.dataset.b; render(); });
    });
    $("flow").querySelectorAll(".probx").forEach(function (x) {
      x.onclick = function (ev) { ev.stopPropagation(); dismissed[x.dataset.x] = true; renderFlow(); };
    });
  }

  // ---- inputs --------------------------------------------------------------
  function renderInputs() {
    var dis = engine ? "" : " disabled";
    var owners = {};
    owners.Board = '<div class="inp"><label for="board">Control board revision</label><select id="board"' + dis + '><option value="A">rev A (original amplifier)</option><option value="B">rev B (alternate amplifier)</option></select></div>';
    owners.Chip = '<div class="inp"><label for="target">Target processor</label><select id="target"' + dis + '><option value="f28004x">F28004x-class (float32)</option><option value="f2803x">F2803x-class (IQ20, legacy)</option></select></div>';
    OPTS.editable.forEach(function (e) {
      var v = e.key in state.edits ? state.edits[e.key] : DATA.inputs[e.key];
      var unit = e.unit === "ratio" ? "V/V" : e.unit === "mohm" ? "mΩ" : e.unit;
      owners[e.owner] = (owners[e.owner] || "") + '<div class="inp"><label for="i-' + esc(e.key) + '">' + esc(e.label) + " (" + esc(unit) + ')</label><input type="number" step="any" min="0" id="i-' + esc(e.key) + '" data-k="' + esc(e.key) + '" value="' + esc(v) + '"' + dis + "></div>";
    });
    var order = [["Product what-if", "overrides the data sheet"], ["Board", "hardware engineer"], ["Chip", "processor"], ["Design choice", "power engineer"]];
    $("inputs").innerHTML = order.map(function (o) {
      return '<div class="card"><h3>' + o[0] + ' <span class="sub" style="font-weight:400">· ' + o[1] + "</span></h3>" + (owners[o[0]] || "") + "</div>";
    }).join("") + '<div class="card"><h3>Reset</h3><p class="sub" style="margin:0 0 6px">Product what-ifs are marked OVERRIDE in the generated C.</p><button id="reset" class="btn" type="button"' + dis + ">Back to shipped product</button></div>";
    $("board").value = state.board; $("target").value = state.target;
    $("board").onchange = function () { state.board = this.value; revealReasonsAfter(300); recompute(); };
    $("target").onchange = function () { state.target = this.value; revealReasonsAfter(300); recompute(); };
    $("reset").onclick = function () { state.edits = {}; state.board = "A"; state.target = "f28004x"; revealReasonsAfter(300); recompute(); };
    var timer = null;
    $("inputs").querySelectorAll("input[data-k]").forEach(function (inp) {
      inp.oninput = function () {
        var x = parseFloat(inp.value);
        if (!(x > 0)) { inp.setCustomValidity("Enter a positive number"); inp.reportValidity(); return; }
        inp.setCustomValidity("");
        state.edits[inp.dataset.k] = x;
        revealReasonsAfter(1500);
        clearTimeout(timer);
        timer = setTimeout(function () {
          var key = inp.dataset.k;
          recompute();
          var again = document.querySelector('input[data-k="' + key + '"]');
          if (again) again.focus();
        }, 400);
      };
    });
  }

  // ---- status bar ------------------------------------------------------------
  function renderGates() {
    var nfail = DATA.constants.filter(function (c) { return c.status === "fail"; }).length;
    var kfail = DATA.checks.filter(function (k) { return k.status === "fail"; }).length;
    var stale = DATA.staleness.filter(function (s) { return s.status === "fail"; }).length;
    var dsb = DATA.datasheet.filter(function (d) { return d.status === "blocking"; }).length;
    var dsf = DATA.datasheet.length - dsb;
    var n = (DATA.changed || []).length;
    var pills = [
      [nfail ? "bad" : "ok", "Constants " + (DATA.constants.length - nfail) + "/" + DATA.constants.length],
      [kfail ? "bad" : "ok", "Checks " + (kfail ? kfail + " failed" : "pass")],
      [dsb ? "bad" : dsf ? "warn" : "ok", "Data sheet " + (dsb ? "blocking" : dsf ? dsf + " for review" : "consistent")],
      [stale ? "bad" : "ok", "Staleness " + (stale ? stale + " stale" : "current")],
      [DATA.ok ? "ok" : "bad", DATA.ok ? "C generated" : "Nothing written (fail closed)"],
      [n ? "chgpill" : "na", n ? n + " value" + (n === 1 ? "" : "s") + " changed vs shipped" : "matches shipped product"]
    ];
    var np = showReasons ? allProblems() : 0;
    $("gates").innerHTML = pills.map(function (p) { return '<span class="pill ' + p[0] + '">' + esc(p[1]) + "</span>"; }).join("") +
      (np ? '<button type="button" class="pill bad probpill" id="probjump">' + np + " problem" + (np === 1 ? "" : "s") + " · show ↓</button>" : "");
    var jump = $("probjump");
    if (jump) jump.onclick = function () {
      var b = firstFailingStage(); if (!b) return;
      state.stage = b; render();
      var el = $("stage-" + b); if (el) el.scrollIntoView({ behavior: "smooth", block: "center" });
    };
  }

  // ---- formulas for the selected stage --------------------------------------
  function eqs(lines) { return lines.map(function (l) { return '<div class="eq"><div class="tex">' + esc(l) + "</div></div>"; }).join(""); }

  function constantBody(c) {
    return '<p class="sub" style="margin:0">' + esc(c.describe) + ' <span class="tag tag-' + c.tag + '">' + esc(TAGNAME[c.tag]) + "</span></p>" +
      (c.message ? '<p class="pill ' + (c.status === "fail" ? "bad" : "na") + '" style="display:inline-block">' + esc(c.message) + "</p>" : "") +
      eqs(c.latex) +
      (c.sources.length ? "<table><tr><th>Input</th><th>From</th><th>Data sheet text / note</th></tr>" + c.sources.map(function (s) {
        return "<tr><td class='mono'>" + esc(s.name) + "</td><td>" + esc(s.origin) + "</td><td>" + esc(s.quote) + "</td></tr>"; }).join("") + "</table>" : "");
  }

  function isOpen(c) { return state.open[c.id] !== undefined ? state.open[c.id] : (c.status === "fail" || changed(c.id)); }

  function renderFormulas() {
    var tabs = [["c", "Generated C"], ["math", "Derivations"], ["diff", "Diff vs shipped"]];
    $("fhead").textContent = state.tab === "math" ? "Derivations · " + DATA.blocks[state.stage] + " (click a stage to switch)" : "Output";
    $("tabs").innerHTML = tabs.map(function (t) { return '<span class="pill tab' + (state.tab === t[0] ? " on" : "") + '" data-t="' + t[0] + '" role="button" tabindex="0">' + t[1] + "</span>"; }).join("");
    $("tabs").querySelectorAll(".tab").forEach(function (e) { keyed(e, function () { state.tab = e.dataset.t; renderFormulas(); }); });
    var out = "";
    if (state.tab === "math") {
      var list = DATA.constants.filter(function (c) { return c.block === state.stage; });
      out = list.map(function (c) {
        var open = isOpen(c);
        return '<div class="frow' + (open ? " open" : "") + '"><button type="button" aria-expanded="' + open + '" data-id="' + esc(c.id) + '">' +
          '<span class="chev">' + (open ? "▾" : "▸") + '</span><span class="sym">' + esc(c.symbol) + '</span><span class="val' + (changed(c.id) ? " chg" : "") + '" data-vid="' + esc(c.id) + '">' + shown(c) + '</span><span class="dot ' + dot(c.status) + '"></span></button>' +
          (open ? '<div class="fbody">' + constantBody(c) + "</div>" : "") + "</div>";
      }).join("");
      var checks = DATA.checks.filter(function (k) { return k.block === state.stage; });
      if (checks.length) {
        out += '<div class="colhead" style="margin-top:16px">Checks on this stage</div>' + checks.map(function (k) {
          return '<p class="sub" style="margin:8px 0 0"><span class="pill ' + (k.status === "ok" ? "ok" : k.status === "fail" ? "bad" : "na") + '">' + esc(k.id) + "</span> " + esc(k.describe) + "</p>" + eqs(k.latex);
        }).join("");
      }
    } else if (state.tab === "c") {
      out = DATA.header ? '<p><a class="btn" id="dl" href="#">Download calgen_' + esc(DATA.variant) + ".h</a></p><pre>" + esc(DATA.header) + "</pre>"
        : '<p class="pill bad" style="display:inline-block">Not generated: ' + esc(DATA.gate_message) + "</p>";
    } else {
      out = DATA.diff ? "<pre>" + DATA.diff.split("\n").map(function (l) {
        var cls = l[0] === "+" && l.slice(0, 3) !== "+++" ? "add" : l[0] === "-" && l.slice(0, 3) !== "---" ? "del" : "";
        return '<span class="' + cls + '">' + esc(l) + "</span>"; }).join("\n") + "</pre>"
        : '<p class="sub">' + (Object.keys(state.edits).length ? "No difference, or nothing generated." : "Change an input to see what changes in the generated C.") + "</p>";
    }
    $("formulas").innerHTML = out;
    $("formulas").querySelectorAll(".frow > button").forEach(function (btn) {
      btn.onclick = function () { var c = byId(btn.dataset.id); state.open[c.id] = !isOpen(c); renderFormulas(); };
    });
    tex($("formulas"));
    var dl = $("dl");
    if (dl) dl.onclick = function (ev) {
      ev.preventDefault();
      var a = document.createElement("a");
      a.href = URL.createObjectURL(new Blob([DATA.header], { type: "text/x-c" }));
      a.download = "calgen_" + DATA.variant + ".h"; a.click(); URL.revokeObjectURL(a.href);
    };
  }

  // ---- flash what just changed -----------------------------------------------
  function flashChanges() {
    if (!prev) return;
    document.querySelectorAll("[data-vid]").forEach(function (el) {
      var c = byId(el.dataset.vid);
      if (c && prev[c.id] !== undefined && prev[c.id] !== c.display) {
        el.classList.remove("flash"); void el.offsetWidth; el.classList.add("flash");
      }
    });
    var sense = document.querySelector(".sense");
    if (sense && prev.__sense !== undefined && prev.__sense !== (DATA.summaries || {}).sense) sense.classList.add("flash");
  }

  function snapshot() {
    var m = {};
    DATA.constants.forEach(function (c) { m[c.id] = c.display; });
    m.__sense = (DATA.summaries || {}).sense;
    return m;
  }

  function firstFailingStage() {
    var c = DATA.constants.filter(function (x) { return x.status === "fail"; })[0];
    if (c) return c.block;
    var k = DATA.checks.filter(function (x) { return x.status === "fail"; })[0];
    return k ? k.block : null;
  }

  function render() { renderTabs(); renderGates(); renderFlow(); renderInputs(); renderFormulas(); flashChanges(); prev = null; }

  function recompute() {
    if (!engine) return;
    $("engine").textContent = "Computing…";
    try {
      var req = JSON.stringify({ product: state.product, board: state.board, target: state.target, edits: state.edits });
      prev = snapshot();
      DATA = JSON.parse(engine.run_json("/calgen/specs", req));
      var bad = firstFailingStage();
      if (bad) state.stage = bad; // show the failure where it happens
      $("engine").textContent = "Live · computed in your browser by calgen";
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
      $("engine").textContent = "Live · the in-browser engine is ready; change an input";
      render();
    } catch (e) {
      $("engine").textContent = "In-browser engine failed to load (" + e.message + "); showing pre-computed results.";
    }
  }
  boot();
})();
