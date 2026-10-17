import pytest

from calgen.units import DIMENSIONLESS, Dim, UnitError, format_dim, parse_unit, to_si


@pytest.mark.parametrize(
    "unit, scale, dim",
    [
        ("V", 1.0, Dim(v=1)),
        ("mohm", 1e-3, Dim(v=1, a=-1)),
        ("Mohm", 1e6, Dim(v=1, a=-1)),
        ("kHz", 1e3, Dim(s=-1)),
        ("MHz", 1e6, Dim(s=-1)),
        ("VA", 1.0, Dim(v=1, a=1)),
        ("V/A", 1.0, Dim(v=1, a=-1)),
        ("1/s", 1.0, Dim(s=-1)),
        ("V^2/W", 1.0, Dim(v=1, a=-1)),
        ("%", 0.01, DIMENSIONLESS),
        ("counts", 1.0, DIMENSIONLESS),
        ("Ah", 3600.0, Dim(a=1, s=1)),
        ("us", 1e-6, Dim(s=1)),
    ],
)
def test_parse_unit(unit, scale, dim):
    s, d = parse_unit(unit)
    assert s == pytest.approx(scale)
    assert d == dim


@pytest.mark.parametrize("bad", ["", "furlong", "V^x", "k%", "mcounts"])
def test_bad_units(bad):
    with pytest.raises(UnitError):
        parse_unit(bad)


def test_to_si():
    assert to_si(10, "mohm") == pytest.approx(0.010)
    assert to_si(20, "kHz") == pytest.approx(20_000)


def test_format_dim_names():
    assert format_dim(Dim(v=1, a=1)) == "W"
    assert format_dim(Dim(v=1, a=-1)) == "ohm"
    assert format_dim(Dim(v=2, s=-1)) == "V^2/s"
