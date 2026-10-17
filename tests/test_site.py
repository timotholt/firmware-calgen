"""The static site builds, every page carries the notice, and nothing loads from outside the site."""

import json
import re
from pathlib import Path

import pytest

from calgen.site import build_site
from calgen.vendor import ASSETS

ROOT = Path(__file__).resolve().parent.parent
VENDOR = ROOT / "vendor"
needs_vendor = pytest.mark.skipif(
    not all((VENDOR / a.name).exists() for a in ASSETS), reason="run `calgen vendor` first (downloads pinned assets)"
)


@pytest.fixture(scope="module")
def site(tmp_path_factory):
    return build_site(ROOT, tmp_path_factory.mktemp("site") / "site", VENDOR)


@needs_vendor
def test_pages_exist_and_carry_notice(site):
    pages = list(site.rglob("*.html"))
    assert {p.name for p in pages} >= {"index.html", "playground.html", "audit.html", "how.html", "ai.html", "magnetics.html", "backstory.html", "fa10507.html", "fa10507_revB.html"}
    for p in pages:
        assert "Results are representative and informational only." in p.read_text(), p


@needs_vendor
def test_no_external_resources(site):
    for p in site.rglob("*.html"):
        text = p.read_text()
        assert not re.search(r'(src|href)="(https?:)?//', text.replace('href="https://github.com/timotholt/firmware-calgen"', "")), p


@needs_vendor
def test_assets_and_bundle(site):
    a = site / "assets"
    for f in ("katex/katex.min.js", "pyodide/pyodide.js", "pyodide/pyodide.asm.wasm", "playground.js", "site.css"):
        assert (a / f).exists(), f
    bundle = json.loads((a / "calgen_bundle.json").read_text())
    assert "src/calgen/playground.py" in bundle and "specs/rules.yaml" in bundle
    assert not any("ti-sdk" in k or k.endswith(".env") for k in bundle)


@needs_vendor
def test_playground_default_data_parses(site):
    html = (site / "playground.html").read_text()
    raw = re.search(r'<script id="default-data" type="application/json">(.*?)</script>', html, re.S).group(1)
    data = json.loads(raw)
    assert data["ok"] and data["variant"].startswith("fa10507") and len(data["constants"]) == 31


@needs_vendor
def test_license_notices_and_ai_optout_on_every_page(site):
    assert (site / "LICENSE.txt").read_text().startswith("firmware-calgen\nCopyright (c) 2026 Timothy Otholt. All rights reserved.")
    assert "Mozilla Public License 2.0" in (site / "THIRD_PARTY_NOTICES.md").read_text()
    assert (site / "assets" / "katex" / "LICENSE").exists()
    for p in site.rglob("*.html"):
        t = p.read_text()
        assert 'name="tdm-reservation" content="1"' in t and 'content="noai, noimageai"' in t, p


@needs_vendor
def test_no_unfilled_template_fields(site):
    for p in site.rglob("*.html"):
        assert not re.search(r"\{(ai|counts|opts|default)\[", p.read_text()), p



@needs_vendor
def test_pages_carry_link_preview_tags(site):
    assert (site / "assets" / "preview.png").exists()
    for p in site.rglob("*.html"):
        text = p.read_text()
        if "<nav>" not in text:
            continue  # only full site pages
        for tag in ('property="og:image"', 'property="og:title"', 'property="og:description"', 'name="twitter:card"'):
            assert tag in text, (p.name, tag)


@needs_vendor
def test_workspace_typography_requires_no_new_font_downloads(site):
    css = (site / 'assets' / 'site.css').read_text()
    # Existing KaTeX math assets are separate; the application UI uses installed system fonts.
    assert 'font-family:system-ui' in css
    assert '@font-face' not in css and '@import' not in css
    assert not re.search(r'url\([^)]*\.(?:woff2?|ttf|otf)', css, re.I)


@needs_vendor
def test_shared_header_is_independent_of_page_content_width(site):
    for name in ['index.html', 'playground.html', 'magnetics.html', 'audit.html', 'how.html', 'ai.html', 'backstory.html', 'reports/index.html']:
        html = (site / name).read_text()
        assert '<header class="site-header"><nav>' in html
        assert html.index('</nav></header>') < html.index('<main>')
        assert '<iframe' not in html
        # Following site navigation bypasses HTML cached from older deployments.
        header = html.split('<header class="site-header">', 1)[1].split('</header>', 1)[0]
        assert 'playground.html?v=' in header and 'magnetics.html?v=' in header
