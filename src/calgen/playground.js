/* Playground front end (plain JavaScript, no framework, no build step).
 * All engineering math runs in Python (calgen.playground) inside the browser
 * via Pyodide; this file only renders its JSON. Every asset is served by this
 * site; nothing is uploaded. */
(function () {
  "use strict";
  var VER = document.currentScript ? new URL(document.currentScript.src).search : ""; // ?v=<content hash>, busts caches
  var DATA = JSON.parse(document.getElementById("default-data").textContent);
  var OPTS = JSON.parse(document.getElementById("options").textContent);
  var state = { product: "FA10507", board: "A", target: "f28004x", edits: {}, stage: "out", open: {}, tab: "changes", preset: null };
  var engine = null;
  var prev = null; // id -> display from the previous computation, for flashing what just changed
  var history = [], inputTimer = null, pendingBefore = null, inputError = "";
  var groupsOpen = { Board: true };
  function copyState() { return JSON.parse(JSON.stringify(state)); }
  function finishPending() {
    clearTimeout(inputTimer);
    if (pendingBefore) { history.push(pendingBefore); pendingBefore = null; }
  }
  function mutate(fn) {
    if (!engine) return;
    finishPending(); history.push(copyState()); inputError = "";
    fn(); recompute();
  }
  function resetProduct() {
    state.board = "A"; state.target = "f28004x"; state.edits = {}; state.preset = null;
    state.stage = "out"; state.open = {}; groupsOpen = { Board: true };
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
    iout_rated: "Rated", iout_trip: "Overload (RMS)", iout_pk_limit: "Peak limit", iout_fs_pk: "Sensor FS", iout_pklim_dac_hi: "High-limit DAC", iout_pklim_dac_lo: "Low-limit DAC", vout_lo: "Output low", vout_hi: "Output high",
    vbat_nom: "Nominal", vbat_cutoff: "Cutoff"
  };
  var INPUT_CHECKS = ["input_voltage_order", "input_frequency_order", "battery_cells_integer", "battery_cells_positive", "output_regulation_nonnegative", "output_regulation_below_100"];
  function inputFinding() { return DATA.checks.find(function (k) { return k.status === 'fail' && INPUT_CHECKS.indexOf(k.id) >= 0; }); }
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
    function suggestion(x) {
      var short = x.key === 'board.r_shunt' ? 'Use a ' + x.value + ' mΩ shunt' : x.key === 'board.g_amp' ? 'Use amp gain ' + x.value + ' V/V' : x.label;
      return '<button type="button" class="applyfix" data-k="' + esc(x.key) + '" data-v="' + x.value + '" title="' + esc(x.label) + '">' + esc(short) + '</button>';
    }
    var h = '<div class="howfix"><b>' + (sugg.length ? 'Try a repair' : 'How to fix') + '</b>';
    if (sugg.length) {
      h += suggestion(sugg[0]);
      if (state.board === 'B') h += '<button type="button" class="applyfix restore-board">Restore original amplifier</button>';
      h += '<p>Hardware changes require engineer review.</p><details><summary>Repair guidance and other options</summary>' +
        fixes.map(function (f) { return '<p>' + esc(f) + '</p>'; }).join('') + sugg.slice(1).map(suggestion).join('') + '</details>';
    } else h += fixes.map(function (f) { return '<p>' + esc(f) + '</p>'; }).join('');
    return h + '</div>';

  }
  function stageBad(b) {
    return DATA.constants.some(function (c) { return c.block === b && c.status === "fail"; }) ||
      DATA.checks.some(function (k) { return k.block === b && k.status === "fail"; }) ||
      (b === "inv" && DATA.staleness.some(function (x) { return x.status === "fail"; }));
  }

  // ---- product and hardware: persistent, separate from market what-ifs ----
  function renderConfiguration() {
    var dis = engine ? "" : " disabled";
    $("configuration").innerHTML = '<label>Product<select id="product"' + dis + '>' + Object.keys(OPTS.products).map(function (k) {
      return '<option value="' + k + '">' + esc(OPTS.products[k]) + '</option>';
    }).join('') + '</select></label>' +
      '<label>Board revision<select id="board" aria-label="Board revision" aria-describedby="board-note"' + dis + '><option value="A">Rev A · original amplifier</option><option value="B">Rev B · alternate amplifier</option></select><small id="board-note" class="hardware-note">Demo board configurations—not actual IntelliPower hardware.</small></label>' +
      '<label>Target processor<select id="target" aria-label="Target processor" aria-describedby="processor-note"' + dis + '><option value="f28004x">F28004x · float32</option><option value="f2803x">F2803x · IQ20</option></select><small id="processor-note" class="hardware-note">Illustrative processor pairing; actual product processor unverified.</small></label>' +
      '<button id="reset" class="btn" type="button" title="Restore this product’s shipped defaults"' + dis + '>↺ Reset</button>';
    $("product").value = state.product; $("board").value = state.board; $("target").value = state.target;
    $("product").onchange = function () { var v = this.value; mutate(function () { state.product = v; resetProduct(); }); };
    $("board").onchange = function () { var v = this.value; mutate(function () {
      state.board = v;
      Object.keys(state.edits).forEach(function (k) { if (k.indexOf("board.") === 0) delete state.edits[k]; });
      groupsOpen.Board = true;
    }); };
    $("target").onchange = function () { var v = this.value; mutate(function () { state.target = v; }); };
    $("reset").onclick = function () { mutate(resetProduct); };
  }

  function renderProductSpecs() {
    var spec = DATA.product_specs;
    if (!spec) return;
    $("product-spec-summary").textContent = 'Product specs · ' + spec.part + ' · ' + spec.brief;
    $("product-spec-content").innerHTML = '<p class="spec-note">Published ratings · read only. Market presets and what-if edits below do not change this reference.</p>' +
      '<div class="spec-table-scroll"><table><thead><tr><th>Rating</th><th>Published value</th><th>Source</th></tr></thead><tbody>' +
      spec.rows.map(function (r) { return '<tr><th scope="row">' + esc(r.label) + '</th><td>' + esc(r.raw) + '</td><td>' + esc(r.source) + '</td></tr>'; }).join('') + '</tbody></table></div>' +
      (spec.findings.length ? '<div class="spec-findings"><b>Source findings and interpretations</b><ul>' + spec.findings.map(function (f) { return '<li>' + esc(f.message) + (f.note ? ' ' + esc(f.note) : '') + '</li>'; }).join('') + '</ul></div>' : '') +
      '<p class="spec-note"><b>Demo assumptions:</b> ' + esc(spec.inverter_assumption) + '. Board sensing, DC bus targets, switching choices, and protection factors are illustrative engineering inputs. <a href="how.html#assumptions">Review assumptions →</a></p>';
  }

  function changeRows(limit) {
    var ids = DATA.changed || [];
    return ids.slice(0, limit || ids.length).map(function (id) {
      var c = byId(id);
      return '<button type="button" data-change="' + esc(id) + '">' + esc(LABEL[id] || c.describe) +
        '<span class="change-value">' + shown(c) + '</span></button>';
    }).join('');
  }
  function bindChanges(el) {
    el.querySelectorAll('[data-change]').forEach(function (button) {
      button.onclick = function () {
        var c = byId(button.dataset.change); state.stage = c.block; state.tab = "math"; state.open[c.id] = true;
        renderFlow(); renderFormulas();
        $("formulas").scrollIntoView({ behavior: "smooth", block: "nearest" });
      };
    });
  }

  // ---- one result, engineering cause first, detailed checks on demand ----
  function renderProbs() {
    var all = [];
    Object.keys(FLOW).forEach(function (b) { all = all.concat(problems(b)); });
    var pending = !!pendingBefore;
    var blocked = !DATA.ok || !!inputError || pending;
    var headline = "Ready for review", message = "The modeled constraints pass. Review the assumptions and source findings before using the generated constants.";
    var invalid = inputFinding();
    var senseFail = DATA.checks.some(function (k) { return k.id === "iout_sense_range" && k.status === "fail"; });
    var busFail = DATA.checks.some(function (k) { return k.id === "bus_above_output_peak" && k.status === "fail"; });
    if (pending) { headline = "Updating your experiment"; message = "Rechecking the edited inputs before generating C."; }
    else if (inputError) { headline = "Check your input"; message = inputError; }
    else if (invalid) { headline = invalid.describe; message = invalid.fix; }
    else if (senseFail && DATA.protection) {
      var p = DATA.protection;
      headline = "Sensor cannot cover the protection limit";
      message = "This configuration needs a " + f1(p.peak_limit) + " A peak limit. The sensor covers ±" + f1(p.sensor_fs) + " A; the " + Math.round(p.headroom * 100) + "% usable range is ±" + f1(p.sensor_fs * p.headroom) + " A.";
    } else if (busFail) {
      headline = "Output exceeds this inverter’s capability";
      message = "The declared bridge stays fixed. Lower the output voltage or review the DC bus and hardware profile.";
    } else if (DATA.staleness.some(function (x) { return x.status === "fail"; })) {
      headline = "Loop gains need review"; message = "The achieved switching frequency differs from the frequency used to tune these gains.";
    } else if (!DATA.ok) {
      headline = "An engineering check failed"; message = "Review the affected input and the check details below. No C is generated while a gate fails.";
    }
    var count = (DATA.changed || []).length;
    var findings = DATA.datasheet || [];
    var h = '<div class="result-status' + (blocked ? ' bad' : '') + '">' + (pending ? 'Updating…' : blocked ? '● Generation blocked' : '✓ C generated · modeled checks pass') + '</div>' +
      '<h2>' + esc(headline) + '</h2><p>' + esc(message) + '</p>';
    if (!pending && !inputError && !DATA.ok) h += fixHtml(all);
    if (findings.length) h += '<div class="review-note"><details><summary>' + findings.length + ' source finding' + (findings.length === 1 ? '' : 's') + ' for review</summary>' + findings.map(function (d) {
      return '<p>' + esc(d.message) + ' ' + esc(d.note) + '</p>';
    }).join('') + '</details></div>';
    h += '<h3>What changed</h3>' + (count ? '<div class="changes-list">' + changeRows(5) + '</div>' + (count > 5 ? '<button class="text-button" id="all-changes">View all ' + count + ' changes →</button>' : '') : '<p>Matches the shipped product’s values.</p>');
    if (all.length && !pending && !inputError) h += '<details><summary>View ' + all.length + ' failed check' + (all.length === 1 ? '' : 's') + '</summary><ul>' + all.map(function (x) { return '<li>' + esc(x.msg) + '</li>'; }).join('') + '</ul></details>';
    h += '<p class="evidence-note">' + (blocked ? 'No C available until the inputs and checks pass.' : 'Synthetic hardware · modeled checks only. Engineering sign-off is still required.') + '</p>';
    $("probs").innerHTML = h;
    $("probs").querySelectorAll('.applyfix').forEach(function (button) {
      button.onclick = function () { mutate(function () { state.edits[button.dataset.k] = parseFloat(button.dataset.v); groupsOpen.Board = true; }); };
    });
    $("probs").querySelectorAll('.restore-board').forEach(function (button) { button.onclick = function () { mutate(function () {
      state.board = 'A'; Object.keys(state.edits).forEach(function (k) { if (k.indexOf('board.') === 0) delete state.edits[k]; });
    }); }; });
    bindChanges($("probs"));
    if ($("all-changes")) $("all-changes").onclick = function () { state.tab = "changes"; renderFormulas(); };
  }

  // ---- current-protection visuals (drawing only; numbers come from Python) ----
  function f1(x) { return (Math.round(x * 100) / 100).toString(); }  // up to 2 decimals: 43.75, not 43.8
  function gaugeSvg(p) {
    if (!p) return "";
    var S = Math.max(p.sensor_fs, p.peak_limit) * 1.1, C = 300, R = 270;
    function x(a) { return C + a / S * R; }
    function rect(cls, a, b) { return '<rect class="' + cls + '" x="' + x(a).toFixed(1) + '" y="28" width="' + (x(b) - x(a)).toFixed(1) + '" height="14"/>'; }
    var over = p.peak_limit > p.headroom * p.sensor_fs;
    var g = '<svg class="viz gauge" viewBox="0 0 600 80" role="img" aria-label="Current sensor range plus or minus ' + f1(p.sensor_fs) +
      " A; hardware peak limit " + f1(p.peak_limit) + " A" + (over ? ", outside the usable range" : "") + '">';
    if (p.peak_limit > p.sensor_fs) g += rect("g-blind", -S, -p.sensor_fs) + rect("g-blind", p.sensor_fs, S);
    g += rect("g-bar", -p.sensor_fs, p.sensor_fs) + rect("g-head", p.headroom * p.sensor_fs, p.sensor_fs) + rect("g-head", -p.sensor_fs, -p.headroom * p.sensor_fs);
    g += '<line class="g-mid" x1="300" y1="24" x2="300" y2="46"/><text class="g-t" x="300" y="60" text-anchor="middle">0 A = mid-rail</text>';
    var marks = [[p.rated_pk, "g-m", "rated " + f1(p.rated_pk) + " A"], [p.crest_pk, "g-m", p.crest + ":1 load " + f1(p.crest_pk) + " A"],
      [p.peak_limit, over ? "g-lim bad" : "g-lim", "limit " + f1(p.peak_limit) + " A"]];
    marks.forEach(function (m, i) {
      [1, -1].forEach(function (sg) { g += '<line class="' + m[1] + '" x1="' + x(sg * m[0]).toFixed(1) + '" y1="24" x2="' + x(sg * m[0]).toFixed(1) + '" y2="46"/>'; });
      g += '<text class="g-t ' + m[1] + '" x="' + x(m[0]).toFixed(1) + '" y="' + (i === 1 ? 74 : 18) + '" text-anchor="middle">' + esc(m[2]) + "</text>";
    });
    g += '<text class="g-t" x="' + x(p.sensor_fs).toFixed(1) + '" y="60" text-anchor="end">sensor ±' + f1(p.sensor_fs) + " A</text>";
    return g + "</svg>";
  }
  // Capacitor-input (computer-type) load: the rectifier conducts only for a short window
  // before each voltage peak, while the line voltage exceeds the capacitor voltage. Drawn as
  // a half-sine current pulse of width W per half-cycle; for crest factor CF the width is
  // W = 2*pi / CF^2 (so the RMS equals the rated current), and the pulse ends just after the
  // voltage peak, so it peaks before it, as measured rectifier currents do.
  function pulse(theta, cf) {
    var w = 2 * Math.PI / (cf * cf), end = Math.PI / 2 + 0.08, start = end - w;
    var t = ((theta % Math.PI) + Math.PI) % Math.PI, sgn = (theta % (2 * Math.PI) + 2 * Math.PI) % (2 * Math.PI) < Math.PI ? 1 : -1;
    return t >= start && t <= end ? sgn * Math.sin(Math.PI * (t - start) / w) : 0;
  }
  function waveSvg(p) {
    if (!p) return "";
    // One cycle of instantaneous current (an RMS threshold has no meaning on this axis),
    // scaled to the hardware limit, with real axes and the headroom the limit leaves.
    var S = Math.max(p.peak_limit, p.crest_pk) * 1.18, W = 600, H = 210, ml = 44, mr = 12, mt = 10, mb = 26;
    var pw = W - ml - mr, ph = H - mt - mb, M = mt + ph / 2, A = ph / 2;
    var over = p.peak_limit > p.headroom * p.sensor_fs, period = 1000 / (p.f_hz || 60);
    function x(t) { return ml + t / (2 * Math.PI) * pw; }
    function y(a) { return M - a / S * A; }
    function hline(cls, a) { return '<line class="' + cls + '" x1="' + ml + '" x2="' + (ml + pw) + '" y1="' + y(a).toFixed(1) + '" y2="' + y(a).toFixed(1) + '"/>'; }
    function path(fn) { var d = ""; for (var i = 0; i <= 400; i++) { var t = i / 400 * 2 * Math.PI; d += (i ? "L" : "M") + x(t).toFixed(1) + " " + y(fn(t)).toFixed(1); } return d; }
    var sw = '<svg class="viz wave" viewBox="0 0 ' + W + " " + H + '" role="img" aria-label="One cycle of output current: a ' + p.crest +
      ":1 rectifier load peaking at " + f1(p.crest_pk) + " A and a linear load peaking at " + f1(p.rated_pk) + " A, both " + f1(p.rated_rms) +
      " A RMS, against a " + f1(p.peak_limit) + ' A hardware limit">';
    if (p.sensor_fs < S) {  // the sensor's blind range, only when it falls inside the plot (rev B)
      sw += '<rect class="w-blind" x="' + ml + '" y="' + mt + '" width="' + pw + '" height="' + (y(p.sensor_fs) - mt).toFixed(1) + '"/>' +
        '<rect class="w-blind" x="' + ml + '" y="' + y(-p.sensor_fs).toFixed(1) + '" width="' + pw + '" height="' + (mt + ph - y(-p.sensor_fs)).toFixed(1) + '"/>';
    }
    // axes: current ticks every 10 or 20 A, time ticks at quarter cycles in ms
    var step = S > 45 ? 20 : 10;
    for (var a = -Math.floor(S / step) * step; a <= S; a += step) {
      sw += '<line class="w-grid" x1="' + ml + '" x2="' + (ml + pw) + '" y1="' + y(a).toFixed(1) + '" y2="' + y(a).toFixed(1) + '"/>' +
        '<text class="g-t" x="' + (ml - 6) + '" y="' + (y(a) + 4).toFixed(1) + '" text-anchor="end">' + a + "</text>";
    }
    for (var q = 0; q <= 4; q++) {
      var tx = ml + q / 4 * pw;
      sw += '<line class="w-axis" x1="' + tx.toFixed(1) + '" x2="' + tx.toFixed(1) + '" y1="' + (mt + ph) + '" y2="' + (mt + ph + 4) + '"/>' +
        '<text class="g-t" x="' + tx.toFixed(1) + '" y="' + (mt + ph + 16) + '" text-anchor="' + (q === 0 ? "start" : q === 4 ? "end" : "middle") + '">' + (period * q / 4).toFixed(1) + (q === 4 ? " ms" : "") + "</text>";
    }
    sw += '<text class="g-t" x="4" y="' + (mt + 10) + '">A</text>';
    sw += '<line class="w-axis" x1="' + ml + '" x2="' + ml + '" y1="' + mt + '" y2="' + (mt + ph) + '"/>' + hline("w-axis", 0);
    sw += hline("w-lim" + (over ? " bad" : ""), p.peak_limit) + hline("w-lim" + (over ? " bad" : ""), -p.peak_limit);
    sw += '<text class="g-t" x="' + (ml + pw - 4) + '" y="' + (y(p.peak_limit) - 5).toFixed(1) + '" text-anchor="end">hardware limit ±' + f1(p.peak_limit) + " A</text>";
    sw += '<path class="w-sine" d="' + path(function (t) { return p.rated_pk * Math.sin(t); }) + '"/>';
    sw += '<path class="w-load" d="' + path(function (t) { return p.crest_pk * pulse(t, p.crest); }) + '"/>';
    // headroom bracket between the first pulse's peak and the limit
    var w = 2 * Math.PI / (p.crest * p.crest), tpk = Math.PI / 2 + 0.08 - w / 2, bx = x(tpk) + 26;
    var y1 = y(p.crest_pk), y2 = y(p.peak_limit), gap = p.peak_limit - p.crest_pk;
    sw += '<line class="w-br' + (over ? " bad" : "") + '" x1="' + bx.toFixed(1) + '" x2="' + bx.toFixed(1) + '" y1="' + y1.toFixed(1) + '" y2="' + y2.toFixed(1) + '"/>' +
      '<line class="w-br' + (over ? " bad" : "") + '" x1="' + (bx - 4).toFixed(1) + '" x2="' + (bx + 4).toFixed(1) + '" y1="' + y1.toFixed(1) + '" y2="' + y1.toFixed(1) + '"/>' +
      '<line class="w-br' + (over ? " bad" : "") + '" x1="' + (bx - 4).toFixed(1) + '" x2="' + (bx + 4).toFixed(1) + '" y1="' + y2.toFixed(1) + '" y2="' + y2.toFixed(1) + '"/>' +
      '<text class="g-t w-brt' + (over ? " bad" : "") + '" x="' + (bx + 8).toFixed(1) + '" y="' + ((y1 + y2) / 2 + 4).toFixed(1) + '">' +
      (over ? "" : f1(gap) + " A headroom (" + Math.round(gap / p.crest_pk * 100) + "%)") + "</text>";
    sw += "</svg>";
    var key = '<div class="wkey">' +
      '<span><i class="k-load"></i>' + p.crest + ":1 rectifier load: " + f1(p.rated_rms) + " A RMS, " + f1(p.crest_pk) + " A peak (illustrative)</span>" +
      '<span><i class="k-sine"></i>linear load: ' + f1(p.rated_rms) + " A RMS, " + f1(p.rated_pk) + " A peak</span>" +
      '<span><i class="k-lim' + (over ? " bad" : "") + '"></i>hardware peak limit: instant</span>' +
      (p.sensor_fs < S ? '<span><i class="k-blind"></i>beyond the sensor\'s ±' + f1(p.sensor_fs) + " A range</span>" : "") + "</div>";
    return sw + key;
  }
  // The other protection layer, in its own units: RMS current against the timed overload trip.
  function rmsBar(p) {
    var mx = p.overload_rms * 1.35, W = 600, ml = 44, mr = 12, pw = W - ml - mr;
    function x(v) { return ml + Math.min(v, mx) / mx * pw; }
    var s = '<svg class="viz rmsbar" viewBox="0 0 ' + W + ' 54" role="img" aria-label="RMS current ' + f1(p.rated_rms) + " A against the " + f1(p.overload_rms) + ' A timed overload trip">' +
      '<text class="g-t" x="4" y="25">RMS</text>' +
      '<rect class="r-bar" x="' + ml + '" y="14" width="' + pw + '" height="16" rx="3"/>' +
      '<rect class="r-val" x="' + ml + '" y="17" width="' + (x(p.rated_rms) - ml).toFixed(1) + '" height="10" rx="2"/>' +
      '<line class="r-trip" x1="' + x(p.overload_rms).toFixed(1) + '" x2="' + x(p.overload_rms).toFixed(1) + '" y1="8" y2="36"/>' +
      '<text class="g-t r-in" x="' + (ml + 6) + '" y="26">either load: ' + f1(p.rated_rms) + ' A RMS</text>' +
      '<text class="g-t r-tript" x="' + (x(p.overload_rms) - 4).toFixed(1) + '" y="48" text-anchor="end">overload trip ' + f1(p.overload_rms) + " A RMS" +
      (p.overload_delay_s ? ", after " + p.overload_delay_s + " s" : "") + " (software)</text></svg>";
    return s + '<p class="wnote">Two protection layers in their own units: the hardware limit acts on every instantaneous peak; the overload acts on RMS current over time.</p>';
  }

  // ---- C syntax highlighting (display only; the download is the raw text) ----
  function hlC(text) {
    var re = /(\/\*[\s\S]*?\*\/)|(^[ \t]*#[ \t]*\w+)|(\b0x[0-9a-fA-F]+[uUlL]*\b|\b\d+(?:\.\d+)?(?:[eE][-+]?\d+)?[fFuUlL]*\b)|(\b(?:UPS|CALGEN)_\w+\b)/gm;
    var out = "", last = 0, m;
    while ((m = re.exec(text))) {
      out += esc(text.slice(last, m.index));
      var cls = m[1] ? (/OVERRIDE/.test(m[1]) ? "c-com c-ovr" : "c-com") : m[2] ? "c-pp" : m[3] ? "c-num" : "c-name";
      out += '<span class="' + cls + '">' + esc(m[0]) + "</span>";
      last = re.lastIndex;
    }
    return out + esc(text.slice(last));
  }

  // ---- selected engineering stage -----------------------------------------------
  function stageBox(b) {
    var rows = FLOW[b].map(function (id) {
      var c = byId(id); if (!c) return "";
      return '<div class="r' + (changed(id) ? " chg" : "") + '" data-vid="' + esc(id) + '" title="' + esc(c.symbol) + '"><span class="lbl">' + esc(LABEL[id] || id) + '</span><span class="rv">' + shown(c) + '</span><span class="tag tag-' + c.tag + '">' + esc(TAGNAME[c.tag]) + "</span></div>";
    }).join("");
    var summary = DATA.summaries ? '<div class="sum">' + esc(DATA.summaries[b]) + "</div>" : "";
    if (b === "out" && DATA.summaries && DATA.summaries.sense) {
      var sat = DATA.summaries.sense.indexOf("SATURATES") >= 0;
      summary += '<div class="sense' + (sat ? " bad" : "") + '">' + esc(DATA.summaries.sense) + "</div>";
      if (DATA.protection) {
        var p = DATA.protection;
        summary = '<div class="vizbox">' + waveSvg(p) + '</div>' +
          '<div class="metric-strip"><div><small>Rated current</small><strong data-vid="iout_rated">' + f1(p.rated_rms) + ' A RMS</strong></div>' +
          '<div><small>Sensor range</small><strong data-vid="iout_fs_pk">±' + f1(p.sensor_fs) + ' A</strong></div><div><small>Peak limit</small><strong data-vid="iout_pk_limit">±' + f1(p.peak_limit) + ' A</strong></div></div>' +
          '<p class="sum">' + esc(DATA.summaries.inv) + '</p>' + rmsBar(p) +
          '<details class="sensor-detail"><summary>Sensor headroom</summary><p class="sum">' + esc(DATA.summaries.sense) + '</p>' + gaugeSvg(p) + '</details>';
      }
    }
    if ((b === 'inv' || b === 'out') && DATA.product_specs) {
      summary += '<p class="inverter-note"><b>Illustrative inverter:</b> ' + esc(DATA.product_specs.inverter_assumption) + '. Topology and PWM are demo assumptions, not verified IntelliPower hardware.</p>';
    }
    var ind = (DATA.inductors || {})[b];
    if (ind) {
      var q = "name=" + encodeURIComponent(ind.name) + "&l=" + ind.l_uh + "&irms=" + ind.i_rms + "&ipk=" + ind.i_pk +
        "&application=" + ind.application + "&ret=" + ind.min_retained + "&from=" + encodeURIComponent(state.product) + "&basis=" + encodeURIComponent(ind.basis);
      summary += '<div class="indlink" title="' + esc(ind.basis) + '">' + esc(ind.name) + " ≈ " + ind.l_uh.toFixed(0) + " µH, " + ind.i_rms.toFixed(1) + " A RMS, " +
        ind.i_pk.toFixed(1) + ' A peak · <a href="magnetics.html#size?' + q + '" class="sizelink">size it in Magnetics →</a></div>';
    }
    return '<article class="fb" id="stage-' + b + '">' + summary +
      '<details class="stage-values"' + (b !== 'out' ? ' open' : '') + '><summary>Stage values and sources</summary>' + rows + '</details></article>';
  }

  function legendHtml() {
    var rows = [
      ['<span class="tag tag-datasheet">data sheet</span>', "Copied from the product's public data sheet"],
      ['<span class="tag tag-derived">derived</span>', "Computed only from data sheet values and public chip facts"],
      ['<span class="tag tag-assumption">assumption</span>', "Computed from an invented board value or design choice (shunt, gain, margin, factor, timing) or a generic chemistry figure"],
      ['<span class="tag tag-design">design</span>', "Engineer-supplied value carried through unchanged (loop gains)"],
      ['<span class="tag tag-override">what-if</span>', "Your override of a data sheet value (marked OVERRIDE in the C)"],
      ['<span class="lgchg"><span class="was">12.5</span> → <b>16.7</b></span>', "Differs from the shipped product (rev A board, F28004x-class, default design)"],
      ['<span class="lgbad">red indicator</span>', "A gate failed in this stage; why, and how to fix it, appear in Results"],
      ["1φ*", "Single-phase is implied by the IEC C14 inlet and NEMA 5-15 outlets, not stated as a rating"]
    ];
    return '<details class="legend"><summary>Sources and assumptions</summary><table>' + rows.map(function (r) {
      return "<tr><td>" + r[0] + "</td><td>" + esc(r[1]) + "</td></tr>";
    }).join("") + "</table></details>";
  }

  function renderFlow() {
    var names = { in: "AC input", rect: "PFC", bus: "DC bus", inv: "Inverter", out: "AC output", batt: "Battery" };
    var title = state.stage === "out" ? "Protection headroom" : DATA.blocks[state.stage];
    $("flow").innerHTML = '<h2 class="stage-heading">' + esc(title) + '</h2><div class="stage-nav-scroll"><div class="stage-nav" aria-label="Power flow stages">' +
      ["in", "rect", "bus", "inv", "out", "batt"].map(function (b) { return '<button type="button" data-b="' + b + '" aria-pressed="' + (state.stage === b) + '" class="flow-stage flow-' + b + ' ' + (stageBad(b) ? 'is-bad' : '') + '">' + '<span>' + names[b] + '</span></button>'; }).join('') +
      '</div></div>' + stageBox(state.stage) + '<div style="padding:0 18px 10px">' + legendHtml() + '</div>';
    $("flow").querySelectorAll('button[data-b]').forEach(function (button) { button.onclick = function () {
      state.stage = button.dataset.b; renderFlow(); renderFormulas();
    }; });
  }

  function field(e, dis) {
    var v = e.key in state.edits ? state.edits[e.key] : DATA.inputs[e.key];
    var base = DATA.shipped_inputs[e.key];
    var unit = e.unit === "ratio" ? "V/V" : e.unit === "mohm" ? "mΩ" : e.unit === "counts" ? "" : e.unit;
    var edited = v != null && v !== base;
    var zeroAllowed = /tol|margin/.test(e.key);
    return '<label class="inp' + (edited ? ' edited' : '') + '"><span>' + esc(e.label) + '</span>' +
      '<input type="number" aria-label="' + esc(e.label + (unit ? " " + unit : "")) + '" step="' + (e.key === 'ds.batt_series_cells' ? '1' : 'any') + '" min="' + (zeroAllowed ? '0' : '0.000001') + '" data-k="' + esc(e.key) + '" value="' + (v == null ? '' : esc(v)) + '"' +
      (v == null ? ' placeholder="n/a" title="not in data sheet"' : '') + dis + '><i class="u">' + esc(unit) + '</i>' +
      (edited ? '<small class="input-origin">Shipped: ' + (base == null ? 'not stated' : esc(base) + ' ' + esc(unit)) + ' · edited</small>' : '') + '</label>';
  }

  function renderInputs() {
    var dis = engine ? '' : ' disabled';
    var groups = {};
    OPTS.editable.forEach(function (e) {
      var group = e.owner.indexOf('Data sheet') === 0 ? e.owner.split(' · ')[1] : e.owner;
      (groups[group] = groups[group] || []).push(e);
    });
    var handEdited = Object.keys(state.edits).some(function (k) { return k.indexOf('ds.') === 0; });
    var presetOpts = '<option value="">As shipped</option>' + Object.keys(OPTS.presets).map(function (k) {
      return '<option value="' + k + '">' + esc(OPTS.presets[k]) + '</option>';
    }).join('') + (handEdited ? '<option value="__custom">Custom · edited by hand</option>' : '');
    var h = '<label class="market-control">What-if market<select id="preset" aria-label="What-if market"' + dis + '>' + presetOpts + '</select><span class="market-note">Hypothetical specification edits, not certified market compatibility.</span></label>';
    ['Board', 'Input', 'Output', 'Overload', 'Design choice', 'Battery'].forEach(function (group) {
      h += '<details class="input-group" data-group="' + group + '"' + (groupsOpen[group] ? ' open' : '') + '><summary>' + esc(group === 'Board' ? 'Board sensing' : group === 'Input' ? 'AC input' : group === 'Output' ? 'Output ratings' : group === 'Design choice' ? 'Design choices' : group) + '</summary><div class="group-fields">' +
        (groups[group] || []).map(function (e) { return field(e, dis); }).join('') + '</div></details>';
    });
    $("inputs").innerHTML = h;
    $("preset").value = handEdited ? '__custom' : state.preset || '';
    $("preset").onchange = function () {
      if (this.value === '__custom') return;
      var value = this.value;
      mutate(function () {
        state.preset = value || null;
        Object.keys(state.edits).forEach(function (k) { if (k.indexOf('ds.') === 0) delete state.edits[k]; });
        groupsOpen.Input = true; groupsOpen.Output = true;
      });
    };
    $("inputs").querySelectorAll('details[data-group]').forEach(function (details) {
      details.ontoggle = function () { if (details.isConnected) groupsOpen[details.dataset.group] = details.open; };
    });
    $("inputs").querySelectorAll('input[data-k]').forEach(function (inp) {
      inp.oninput = function () {
        var x = Number(inp.value), key = inp.dataset.k;
        if (!inp.value || !Number.isFinite(x) || x < Number(inp.min)) {
          clearTimeout(inputTimer); inputError = 'Enter a ' + (Number(inp.min) === 0 ? 'non-negative' : 'positive') + ' number for ' + inp.closest('label').querySelector('span').textContent + '.';
          $("engine").textContent = 'Input needs attention'; renderProbs(); renderFormulas(); return;
        }
        inputError = '';
        if (!pendingBefore) pendingBefore = copyState();
        state.edits[key] = x;
        $("engine").textContent = 'Updating…';
        renderProbs(); renderFormulas();
        clearTimeout(inputTimer);
        inputTimer = setTimeout(function () {
          finishPending(); recompute();
          var again = document.querySelector('input[data-k="' + key + '"]');
          if (again) again.focus();
        }, 250);
      };
    });
    var n = Object.keys(state.edits).length + (state.board !== 'A' ? 1 : 0) + (state.target !== 'f28004x' ? 1 : 0) + (state.preset ? 1 : 0);
    $("input-actions").innerHTML = '<span>' + (n ? n + ' experiment change' + (n === 1 ? '' : 's') : 'Shipped defaults') + '</span><button type="button" class="text-button" id="undo"' + (history.length ? '' : ' disabled') + '>↶ Undo</button>';
    $("undo").onclick = function () {
      finishPending();
      if (!history.length) return;
      state = history.pop(); inputError = ''; recompute();
    };
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
    var tabs = [["changes", "Changes"], ["math", "Derivations"], ["c", "Generated C"], ["diff", "Diff vs shipped"]];
    $("fhead").textContent = state.tab === "math" ? "Derivations · " + DATA.blocks[state.stage] + " (click a stage to switch)" : "Output";
    $("tabs").innerHTML = tabs.map(function (t) { return '<button type="button" class="pill tab' + (state.tab === t[0] ? " on" : "") + '" data-t="' + t[0] + '" aria-pressed="' + (state.tab === t[0]) + '">' + t[1] + "</button>"; }).join("");
    $("tabs").querySelectorAll(".tab").forEach(function (e) {
      keyed(e, function () {
        state.tab = e.dataset.t; renderFormulas();
      });
    });
    var out = "";
    if (inputError || pendingBefore) {
      out = '<p class="sub">' + esc(inputError || 'Rechecking your changes…') + ' C downloads are unavailable until the inputs pass.</p>';
    } else if (state.tab === "changes") {
      var changedConstants = DATA.constants.filter(function (c) { return changed(c.id); });
      out = changedConstants.length ? '<table class="change-table"><thead><tr><th>Constant</th><th>Shipped</th><th>Current</th></tr></thead><tbody>' + changedConstants.map(function (c) {
        return '<tr><td><button type="button" class="text-button" data-change="' + esc(c.id) + '">' + esc(c.symbol) + '</button></td><td class="mono">' + esc(DATA.baseline[c.id]) + '</td><td>' + esc(c.display) + '</td></tr>';
      }).join('') + '</tbody></table>' : '<p class="sub">Your starting point matches the shipped product. Change a board, processor, or input to compare the results here.</p>';
    } else if (state.tab === "math") {
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
      out = DATA.header ? '<p><a class="btn" id="dl" href="#">Download calgen_' + esc(DATA.variant) + ".h</a></p><pre class=\"code\">" + hlC(DATA.header) + "</pre>"
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
    bindChanges($("formulas"));
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
    var invalid = inputFinding(); if (invalid) return invalid.block;
    var c = DATA.constants.filter(function (x) { return x.status === "fail"; })[0];
    if (c) return c.block;
    var k = DATA.checks.filter(function (x) { return x.status === "fail"; })[0];
    return k ? k.block : DATA.staleness.some(function (x) { return x.status === "fail"; }) ? "inv" : null;
  }

  function render() { renderConfiguration(); renderProductSpecs(); renderProbs(); renderFlow(); renderInputs(); renderFormulas(); flashChanges(); prev = null; }

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
      inputError = "Unable to recheck these inputs: " + e.message;
      $("engine").textContent = "Engine needs attention";
    }
    render();
  }

  async function boot() {
    render();
    if (typeof loadPyodide !== "function") { $("engine").textContent = "In-browser engine unavailable; showing pre-computed results."; return; }
    try {
      var py = await loadPyodide({ indexURL: new URL("assets/pyodide/", location.href).href });
      await py.loadPackage(new URL("assets/pyodide/pyyaml-6.0.2-cp312-cp312-pyodide_2024_0_wasm32.whl", location.href).href);
      var files = await (await fetch("assets/calgen_bundle.json" + VER)).json();
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
