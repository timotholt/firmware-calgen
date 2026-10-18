/* Apply before paint; one button switches themes and remembers the choice. */
(function () {
  'use strict';
  var root = document.documentElement;
  var media = window.matchMedia('(prefers-color-scheme: dark)');
  var chosen = null;
  try { chosen = localStorage.getItem('calgen-theme'); } catch (e) { /* storage may be unavailable */ }
  if (chosen !== 'light' && chosen !== 'dark') chosen = null;
  function apply(theme) {
    root.dataset.theme = theme;
    var button = document.getElementById('theme-toggle');
    if (button) {
      button.setAttribute('aria-pressed', String(theme === 'dark'));
      button.title = theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode';
    }
  }
  apply(chosen || (media.matches ? 'dark' : 'light'));
  document.addEventListener('DOMContentLoaded', function () {
    apply(root.dataset.theme);
    document.getElementById('theme-toggle').addEventListener('click', function () {
      chosen = root.dataset.theme === 'dark' ? 'light' : 'dark';
      try { localStorage.setItem('calgen-theme', chosen); } catch (e) { /* keep the current-page toggle usable */ }
      apply(chosen);
    });
  });
  media.addEventListener('change', function () { if (!chosen) apply(media.matches ? 'dark' : 'light'); });
  window.addEventListener('storage', function (event) {
    if (event.key !== 'calgen-theme') return;
    chosen = event.newValue === 'dark' || event.newValue === 'light' ? event.newValue : null;
    apply(chosen || (media.matches ? 'dark' : 'light'));
  });
}());
