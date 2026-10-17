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
    if (q && (r.id + " " + r.title + " " + r.core + " " + r.material).toLowerCase().indexOf(q) < 0) return false;
    return true;
  }

  function renderList() {
    var rows = DATA.records.filter(matches);
    $("m-count").textContent = rows.length + " of " + DATA.records.length + " drawings";
    $("m-list").innerHTML = rows.map(function (r) {
      return '<tr class="mrow' + (r.id === sel ? " on" : "") + '" data-id="' + esc(r.id) + '" tabindex="0"><td class="mono">' + esc(r.id) + "</td><td>" + esc(r.title) +
        '</td><td class="mono">' + esc(r.core) + "</td><td>" + esc(r.l_text) + "</td><td>" + r.i_a + " A</td><td>" +
        (r.flagged ? '<span class="pill bad">review</span>' : '<span class="pill ok">pass</span>') + "</td></tr>";
    }).join("") || '<tr><td colspan="6" class="sub">No drawings match these filters.</td></tr>';
    $("m-list").querySelectorAll(".mrow").forEach(function (tr) {
      tr.onclick = function () { sel = tr.dataset.id; render(); };
      tr.onkeydown = function (ev) { if (ev.key === "Enter") { sel = tr.dataset.id; render(); } };
    });
  }

  function renderDetail() {
    var r = byId[sel];
    var fields = [["Drawing", r.id + " rev " + r.rev, "id"], ["Title", r.title, "title"], ["Core", r.core + " (" + r.core_desc + ")", "core"]];
    if (r.kind === "inductor") {
      fields.push(["Inductance", r.l_text, "l_text"]);
    } else {
      fields.push(["Magnetizing inductance (min)", r.l_text, "lm_text"], ["Turns ratio", r.source.ratio_text || "", "ratio_text"]);
    }
    r.windings.forEach(function (w) {
      fields.push(["Winding " + w.name, w.turns + " turns, " + w.strands + " × " + w.awg + " AWG, " + w.i_rms_a + " A RMS", w.name]);
    });
    var html = '<div class="mdetail"><div class="mdraw"><a href="magnetics/' + esc(r.id) + '.pdf" target="_blank" rel="noopener" title="Open the PDF">' +
      '<img src="magnetics/' + esc(r.id) + '.png" alt="Drawing ' + esc(r.id) + ': ' + esc(r.title) + '" width="1268" height="980"></a>' +
      '<p class="sub"><a href="magnetics/' + esc(r.id) + '.pdf" target="_blank" rel="noopener">Open the PDF</a> · synthetic drawing; the fields on the right were read from this PDF</p></div>' +
      '<div class="minfo"><h3>Extracted from the PDF text</h3><table><tr><th>Field</th><th>Value</th><th>Text it came from</th></tr>' +
      fields.map(function (f) { return "<tr><td>" + esc(f[0]) + "</td><td>" + esc(f[1]) + '</td><td class="mono sub">' + esc(r.source[f[2]] || "") + "</td></tr>"; }).join("") +
      "</table></div></div>";
    html += '<h3>Physics checks</h3>' + r.checks.map(function (c) {
      var cls = c.status === "pass" ? "ok" : c.status === "flag" ? "bad" : "na";
      return '<div class="mcheck"><p><span class="pill ' + cls + '">' + esc(c.status === "flag" ? "review" : c.status) + "</span> <b>" + esc(c.title) + "</b> · " + esc(c.message) + "</p>" +
        c.latex.map(function (l) { return '<div class="eq"><div class="tex">' + esc(l) + "</div></div>"; }).join("") + "</div>";
    }).join("");
    html += '<h3>Closest past designs</h3><p class="sub">Same kind, ranked by closeness of inductance, current, and turns. In real use this answers "have we built something like this before?"</p><ul class="msim">' +
      r.similar.map(function (s) { var o = byId[s.id]; return '<li><a href="#" data-id="' + esc(s.id) + '">' + esc(s.id) + "</a> " + esc(o.title) + " · " + esc(o.l_text) + ", " + o.i_a + " A" + (o.flagged ? ' <span class="pill bad">review</span>' : "") + "</li>"; }).join("") + "</ul>";
    $("m-detail").innerHTML = html;
    $("m-detail").querySelectorAll(".msim a").forEach(function (a) { a.onclick = function (ev) { ev.preventDefault(); sel = a.dataset.id; render(); }; });
    tex($("m-detail"));
  }

  function render() { renderList(); renderDetail(); }
  ["f-kind", "f-status", "f-text", "f-lmin", "f-lmax", "f-imin"].forEach(function (id) { $(id).oninput = renderList; $(id).onchange = renderList; });
  $("f-reset").onclick = function () { ["f-text", "f-lmin", "f-lmax", "f-imin"].forEach(function (id) { $(id).value = ""; }); $("f-kind").value = ""; $("f-status").value = ""; renderList(); };
  render();
})();
