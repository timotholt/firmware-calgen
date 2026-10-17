import re
from pathlib import Path

from calgen.build import build
from calgen.report import NOTICE, render_report
from calgen.spec import load_rules, load_variant

SPECS = Path(__file__).resolve().parent.parent / "specs"
RULES = load_rules(SPECS / "rules.yaml")


def page(name, previous=""):
    return render_report(build(load_variant(SPECS / "variants" / f"{name}.yaml"), RULES), previous)


def test_notice_is_first_thing_on_the_page():
    html = page("fa10507")
    body = html.split("<main>", 1)[1]
    assert body.lstrip().startswith('<div class="notice">')
    assert "Results are representative and informational only." in NOTICE


def test_every_constant_has_a_list_item_and_a_pane():
    html = page("fa10507")
    items = set(re.findall(r'class="it[^"]*" data-id="([^"]+)"', html))
    panes = set(re.findall(r'class="pane" id="p-([^"]+)"', html))
    assert items == panes and len(items) == len(RULES.constants)


def test_failing_build_shows_why_and_no_header():
    html = page("fa10507_revB")
    assert "Nothing written (fail closed)" in html
    assert "sensor saturates before the trip fires" in html
    assert 'class="it start" data-id="iout_trip_dac_lo"' in html  # opens on the first failure


def test_self_contained_no_external_urls():
    html = page("fa10434")
    assert not re.search(r'(src|href)="https?://', html)


def test_diff_against_previous_version():
    html = page("fa10507", previous="#define OLD 1\n")
    assert 'class="del">-#define OLD 1' in html
