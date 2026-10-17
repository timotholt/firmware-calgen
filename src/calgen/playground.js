/* Playground front end (plain JavaScript, no framework, no build step).
 * All engineering math runs in Python (calgen.playground) inside the browser
 * via Pyodide; this file only renders its JSON. Every asset is served by this
 * site; nothing is uploaded. */
(function () {
  "use strict";
  var DATA = JSON.parse(document.getElementById("default-data").textContent);
  var OPTS = JSON.parse(document.getElementById("options").textContent);
  var state = { product: "FA10507", board: "A", target: "f28004x", edits: {}, stage: "out", open: {}, tab: "c", preset: null, scenario: "shipped" };
  var engine = null;
  var prev = null; // id -> display from the previous computation, for flashing what just changed
  var showReasons = true; // reasons appear only after the user pauses (red borders appear at once)
  var reasonTimer = null;
  function revealReasonsAfter(ms) {
    showReasons = false;
    clearTimeout(reasonTimer);
    reasonTimer = setTimeout(function () { showReasons = true; renderProbs(); renderGates(); }, ms);
  }
  var FLOW = {
    "in": ["vin_min", "vin_max", "fin_min", "fin_max", "iin_limit"],
    "rect": ["vbus_min"],
    "bus": ["vbus_set", "vbus_fs"],
    "inv": ["vout_set", "fout_hz", "fout_mode", "pwm_period"],
    "out": ["iout_rated", "iout_trip", "iout_pk_limit", "iout_fs_pk", "iout_pklim_dac_hi"],
    "batt": ["vbat_nom", "vbat_cutoff"]
  };
  var LABEL = {
    vin_min: "Vin min", vin_max: "Vin max", fin_min: "Fin min", fin_max: "Fin max", iin_limit: "Iin max",
    vbus_min: "Bus min", vbus_set: "Bus setpoint", vbus_fs: "Bus sensor FS",
    vout_set: "Vout", fout_hz: "Fout", fout_mode: "Mode", pwm_period: "PWM period",
    iout_rated: "Rated", iout_trip: "Overload (RMS)", iout_pk_limit: "Peak limit", iout_fs_pk: "Sensor FS", iout_pklim_dac_hi: "Limit DAC",
    vbat_nom: "Nominal", vbat_cutoff: "Cutoff"
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
    var out = DATA.constants.filter(function (c) { return c.block === b && c.status === "fail"; })
      .map(function (c) { return { msg: c.symbol + ": " + c.message, fix: "", suggest: c.suggest || [] }; });
    out = out.concat(DATA.checks.filter(function (k) { return k.block === b && k.status === "fail"; })
      .map(function (k) { return { msg: k.message, fix: k.fix || "", suggest: k.suggest || [] }; }));
    if (b === "inv") out = out.concat(DATA.staleness.filter(function (x) { return x.status === "fail"; })
      .map(function (x) { return { msg: x.param + ": " + x.message, fix: "Re-tune the loop gains for the new frequency, or set the switching frequency back.", suggest: [] }; }));
    return out;
  }

  function fixHtml(probs) {
    var fixes = [], seenFix = {}, sugg = [], seenKey = {};
    probs.forEach(function (p) {
      if (p.fix && !seenFix[p.fix]) { seenFix[p.fix] = 1; fixes.push(p.fix); }
      p.suggest.forEach(function (x) { if (!seenKey[x.key + x.value]) { seenKey[x.key + x.value] = 1; sugg.push(x); } });
    });
    if (!fixes.length && !sugg.length) return "";
    return '<div class="howfix"><b>How to fix</b>' + fixes.map(function (f) { return "<p>" + esc(f) + "</p>"; }).join("") +
      sugg.map(function (x) { return '<button type="button" class="applyfix" data-k="' + esc(x.key) + '" data-v="' + x.value + '">Apply: ' + esc(x.label) + "</button>"; }).join("") + "</div>";
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
      keyed(e, function () {
        if (!engine || e.dataset.p === state.product) return;
        state.product = e.dataset.p; state.open = {};
        applyScenario(state.scenario === "custom" ? "shipped" : state.scenario); // same change request, other product
      });
    });
  }

  // ---- scenarios (guided what-ifs) --------------------------------------------
  function applyScenario(k) {
    var sc = OPTS.scenarios[k];
    state.scenario = k; state.board = sc.board; state.target = sc.target; state.preset = sc.preset;
    state.edits = JSON.parse(JSON.stringify(sc.edits));
    revealReasonsAfter(300); recompute();
  }
  function goCustom() { state.scenario = "custom"; }

  function renderScenarios() {
    var outcomes = (OPTS.outcomes || {})[state.product] || {};
    $("scen").innerHTML = Object.keys(OPTS.scenarios).map(function (k) {
      var on = state.scenario === k, ok = outcomes[k];
      var mark = ok === undefined ? "" : '<span class="om ' + (ok ? "ok" : "bad") + '" title="' + (ok ? "builds: C generated" : "blocked: a gate refuses to write C") + '">' + (ok ? "✓ builds" : "✗ blocked") + "</span>";
      return '<button type="button" class="scn' + (on ? " on" : "") + '" role="radio" aria-checked="' + on + '" data-s="' + k + '"' + (engine ? "" : " disabled") + ">" +
        '<span class="rd" aria-hidden="true"></span><span class="sl">' + esc(OPTS.scenarios[k].label) + "</span>" + mark + "</button>";
    }).join("");
    $("scen").querySelectorAll(".scn").forEach(function (b) { b.onclick = function () { applyScenario(b.dataset.s); }; });
    var sc = OPTS.scenarios[state.scenario];
    var story = sc ? "<b>" + esc(sc.label) + "</b><p>" + esc(sc.story) + "</p>"
      : "<b>Custom edits</b><p>You changed inputs by hand. Pick a scenario above to start again from it.</p>";
    var result = DATA.ok ? '<p class="res ok">C generated · ' + ((DATA.changed || []).length ? (DATA.changed || []).length + " values differ from the shipped product" : "matches the shipped product") + "</p>"
      : '<p class="res bad">Blocked · nothing written (fail closed)</p>';
    $("story").innerHTML = story + result;
  }

  // ---- why it's blocked, and how to fix (left column, no overlap) -----------
  function renderProbs() {
    var stages = Object.keys(FLOW).filter(function (b) { return problems(b).length; });
    if (!stages.length || !showReasons) { $("probs").innerHTML = ""; return; }
    $("probs").innerHTML = '<div class="probs" role="alert"><b>Why it is blocked</b>' + stages.map(function (b) {
      var probs = problems(b);
      return '<div class="pst"><button type="button" class="pstage" data-b="' + b + '">' + esc(DATA.blocks[b]) + " →</button><ul>" +
        probs.map(function (m) { return "<li>" + esc(m.msg) + "</li>"; }).join("") + "</ul>" + fixHtml(probs) + "</div>";
    }).join("") + "</div>";
    $("probs").querySelectorAll(".pstage").forEach(function (x) {
      x.onclick = function () { state.stage = x.dataset.b; state.tab = "math"; render(); var el = $("stage-" + x.dataset.b); if (el) el.scrollIntoView({ behavior: "smooth", block: "nearest" }); };
    });
    $("probs").querySelectorAll(".applyfix").forEach(function (btn) {
      btn.onclick = function () { goCustom(); state.edits[btn.dataset.k] = parseFloat(btn.dataset.v); revealReasonsAfter(300); recompute(); };
    });
  }

  // ---- vertical power flow -----------------------------------------------
  function stageBox(b) {
    var rows = FLOW[b].map(function (id) {
      var c = byId(id); if (!c) return "";
      return '<div class="r' + (changed(id) ? " chg" : "") + '" data-vid="' + esc(id) + '" title="' + esc(c.symbol) + '"><span class="lbl">' + esc(LABEL[id] || id) + '</span><span class="rv">' + shown(c) + '</span><span class="tag tag-' + c.tag + '">' + esc(TAGNAME[c.tag]) + "</span></div>";
    }).join("");
    var summary = DATA.summaries ? '<div class="sum">' + esc(DATA.summaries[b]) + "</div>" : "";
    if (b === "out" && DATA.summaries && DATA.summaries.sense) {
      var sat = DATA.summaries.sense.indexOf("SATURATES") >= 0;
      summary += '<div class="sense' + (sat ? " bad" : "") + '">' + esc(DATA.summaries.sense) + "</div>";
    }
    var any = DATA.constants.some(function (c) { return c.block === b && changed(c.id); });
    return '<div class="fb' + (state.stage === b ? " sel" : "") + (stageBad(b) ? " bad" : "") + (any ? " has-chg" : "") +
      '" data-b="' + b + '" id="stage-' + b + '" role="button" tabindex="0" aria-pressed="' + (state.stage === b) + '"><div class="t">' + esc(DATA.blocks[b]) + "</div>" + summary + rows + "</div>";
  }

  function legendHtml() {
    var rows = [
      ['<span class="tag tag-datasheet">data sheet</span>', "Copied from the product's public data sheet"],
      ['<span class="tag tag-derived">derived</span>', "Computed only from data sheet values and public chip facts"],
      ['<span class="tag tag-assumption">assumption</span>', "Computed using an invented board part, design margin, or generic chemistry figure"],
      ['<span class="tag tag-design">design</span>', "Engineer-supplied value (loop gain), carried through unchanged"],
      ['<span class="tag tag-override">what-if</span>', "Your override of a data sheet value (marked OVERRIDE in the C)"],
      ['<span class="lgchg"><span class="was">12.5</span> → <b>16.7</b></span>', "Differs from the shipped product (rev A board, F28004x-class, default design)"],
      ['<span class="lgbad">red border</span>', "A gate failed in this stage; why, and how to fix it, appear on the left"],
      ["1φ*", "Single-phase is implied by the IEC C14 inlet and NEMA 5-15 outlets, not stated as a rating"]
    ];
    return '<div class="legend"><div class="colhead">Legend</div><table>' + rows.map(function (r) {
      return "<tr><td>" + r[0] + "</td><td>" + esc(r[1]) + "</td></tr>";
    }).join("") + "</table></div>";
  }

  function renderFlow() {
    var down = '<div class="vdown" aria-hidden="true">↓</div>';
    $("flow").innerHTML = stageBox("in") + down + stageBox("rect") + down +
      '<div class="busrow">' + stageBox("bus") + '<div class="side" aria-hidden="true">↔</div>' + stageBox("batt") + "</div>" +
      down + stageBox("inv") + down + stageBox("out") +
      legendHtml();
    $("flow").querySelectorAll(".fb").forEach(function (e) {
      keyed(e, function () { state.stage = e.dataset.b; render(); });
    });
  }

  // ---- inputs --------------------------------------------------------------
  function field(e, dis) {
    var v = e.key in state.edits ? state.edits[e.key] : DATA.inputs[e.key];
    var unit = e.unit === "ratio" ? "V/V" : e.unit === "mohm" ? "mΩ" : e.unit === "counts" ? "" : e.unit;
    var edited = e.key in state.edits || (state.preset && e.key.indexOf("ds.") === 0 && DATA.inputs[e.key] !== DATA.shipped_inputs[e.key]);
    return '<label class="inp' + (edited ? " edited" : "") + '"><span>' + esc(e.label) + "</span>" +
      '<input type="number" step="any" min="0" data-k="' + esc(e.key) + '" value="' + (v == null ? "" : esc(v)) + '"' +
      (v == null ? ' placeholder="n/a" title="not in data sheet"' : "") + dis + '><i class="u">' + esc(unit) + "</i></label>";
  }

  function renderInputs() {
    var dis = engine ? "" : " disabled";
    var groups = {};
    OPTS.editable.forEach(function (e) { (groups[e.owner] = groups[e.owner] || []).push(e); });
    var dsGroups = Object.keys(groups).filter(function (g) { return g.indexOf("Data sheet") === 0; });
    var presetOpts = '<option value="">As shipped (data sheet)</option>' + Object.keys(OPTS.presets).map(function (k) {
      return '<option value="' + k + '"' + (state.preset === k ? " selected" : "") + ">" + esc(OPTS.presets[k]) + "</option>";
    }).join("");
    var ds = '<div class="card dsbox"><div class="dshead"><h3>Data sheet values <span class="sub" style="font-weight:400">· what-if: edits override the data sheet and are marked OVERRIDE in the C</span></h3>' +
      '<label class="inp preset' + (state.preset ? " edited" : "") + '"><span>Market preset</span><select id="preset"' + dis + ">" + presetOpts + "</select></label></div>" +
      '<div class="dsgrid">' + dsGroups.map(function (g) {
        return '<div><div class="glabel">' + esc(g.split(" · ")[1]) + "</div>" + groups[g].map(function (e) { return field(e, dis); }).join("") + "</div>";
      }).join("") + "</div></div>";
    var board = '<div class="card"><h3>Board and chip <span class="sub" style="font-weight:400">· hardware engineer</span></h3>' +
      '<label class="inp' + (state.board !== "A" ? " edited" : "") + '"><span>Board revision</span><select id="board"' + dis + '><option value="A">rev A (original amplifier)</option><option value="B">rev B (alternate amplifier)</option></select></label>' +
      (groups.Board || []).map(function (e) { return field(e, dis); }).join("") +
      '<label class="inp' + (state.target !== "f28004x" ? " edited" : "") + '"><span>Target processor</span><select id="target"' + dis + '><option value="f28004x">F28004x-class (float32)</option><option value="f2803x">F2803x-class (IQ20, legacy)</option></select></label></div>';
    var design = '<div class="card"><h3>Design choice <span class="sub" style="font-weight:400">· power engineer</span></h3>' +
      (groups["Design choice"] || []).map(function (e) { return field(e, dis); }).join("") +
      '<button id="reset" class="btn" type="button"' + dis + ' style="margin-top:8px">Back to shipped product</button></div>';
    $("inputs").innerHTML = ds + '<div class="inrow">' + board + design + "</div>";
    $("board").value = state.board; $("target").value = state.target;
    $("board").onchange = function () { goCustom(); state.board = this.value; revealReasonsAfter(300); recompute(); };
    $("target").onchange = function () { goCustom(); state.target = this.value; revealReasonsAfter(300); recompute(); };
    $("preset").onchange = function () {
      goCustom();
      state.preset = this.value || null;
      Object.keys(state.edits).forEach(function (k) { if (k.indexOf("ds.") === 0) delete state.edits[k]; });
      revealReasonsAfter(300); recompute();
    };
    $("reset").onclick = function () { applyScenario("shipped"); };
    var timer = null;
    $("inputs").querySelectorAll("input[data-k]").forEach(function (inp) {
      inp.oninput = function () {
        var x = parseFloat(inp.value);
        if (!(x > 0)) { inp.setCustomValidity("Enter a positive number"); inp.reportValidity(); return; }
        inp.setCustomValidity("");
        goCustom();
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
    var notOk = pills.filter(function (p) { return p[0] !== "ok"; });
    var shownPills = notOk.length === pills.length ? pills : [["ok", "All gates pass ✓"]].concat(notOk);
    if (pills.slice(0, 5).some(function (p) { return p[0] === "bad"; })) shownPills = pills;
    $("gates").innerHTML = shownPills.map(function (p) { return '<span class="pill ' + p[0] + '">' + esc(p[1]) + "</span>"; }).join("") +
      (np ? '<button type="button" class="pill bad probpill" id="probjump">' + np + " problem" + (np === 1 ? "" : "s") + " · see why ←</button>" : "");
    var jump = $("probjump");
    if (jump) jump.onclick = function () { $("probs").scrollIntoView({ behavior: "smooth", block: "nearest" }); };
  }

  // ---- formulas for the selected stage --------------------------------------
  function eqs(lines) { return lines.map(function (l) { return '<div class="eq"><div class="tex">' + esc(l) + "</div></div>"; }).join(""); }

  function constantBody(c) {
    return '<p class="sub" style="margin:0">' + esc(c.describe) + ' <span class="tag tag-' + c.tag + '">' + esc(TAGNAME[c.tag]) + "</span></p>" +
      (c.message ? '<p class="alert ' + (c.status === "fail" ? "bad" : "na") + '">' + esc(c.message) + "</p>" : "") +
      eqs(c.latex) +
      (c.sources.length ? "<table><tr><th>Input</th><th>From</th><th>Data sheet text / note</th></tr>" + c.sources.map(function (s) {
        return "<tr><td class='mono'>" + esc(s.name) + "</td><td>" + esc(s.origin) + "</td><td>" + esc(s.quote) + "</td></tr>"; }).join("") + "</table>" : "");
  }

  function isOpen(c) { return state.open[c.id] !== undefined ? state.open[c.id] : c.status === "fail"; } // changed rows show old -> new in the row itself

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
        : '<p class="alert bad">Not generated: ' + esc(DATA.gate_message) + "</p>";
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

  function render() { renderTabs(); renderGates(); renderScenarios(); renderProbs(); renderFlow(); renderInputs(); renderFormulas(); flashChanges(); prev = null; }

  function recompute() {
    if (!engine) return;
    $("engine").textContent = "Computing…";
    try {
      var req = JSON.stringify({ product: state.product, board: state.board, target: state.target, edits: state.edits, preset: state.preset });
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
