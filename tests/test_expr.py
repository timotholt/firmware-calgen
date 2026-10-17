import pytest

from calgen.expr import ExprError, Quantity, evaluate, parse
from calgen.units import Dim, UnitError

V, A, OHM, HZ = Dim(v=1), Dim(a=1), Dim(v=1, a=-1), Dim(s=-1)

ENV = {
    "ds.power_va": Quantity(1500.0, Dim(v=1, a=1)),
    "ds.vout_nom": Quantity(120.0, V),
    "board.r_shunt": Quantity(0.010, OHM),
    "board.g_amp": Quantity(20.0),
    "target.v_ref": Quantity(3.3, V),
    "target.f_pwmclk": Quantity(100e6, HZ),
    "design.f_sw": Quantity(20e3, HZ),
}


def ev(src):
    return evaluate(parse(src), ENV)


def test_rated_current_has_amp_units():
    q = ev("ds.power_va / ds.vout_nom")
    assert q.value == pytest.approx(12.5)
    assert q.dim == A


def test_sense_full_scale():
    q = ev("target.v_ref / (board.r_shunt * board.g_amp)")
    assert q.value == pytest.approx(16.5)
    assert q.dim == A


def test_pwm_period_is_dimensionless():
    q = ev("target.f_pwmclk / design.f_sw")
    assert q.value == pytest.approx(5000)
    assert q.dim == Dim()


def test_adding_volts_to_amps_fails():
    with pytest.raises(UnitError, match="cannot add"):
        ev("ds.vout_nom + ds.power_va / ds.vout_nom")


def test_sqrt_and_pow():
    q = ev("sqrt(2) * ds.vout_nom")
    assert q.value == pytest.approx(169.7056, rel=1e-6)
    assert ev("ds.vout_nom ** 2 / board.r_shunt").dim == Dim(v=1, a=1)


def test_sqrt_of_non_square_unit_fails():
    with pytest.raises(UnitError):
        ev("sqrt(ds.vout_nom)")


def test_min_max_round():
    q = ev("max(ds.vout_nom, target.v_ref)")
    assert q.value == 120.0 and q.dim == V
    assert ev("round(2.5)").value == 2.0  # half-to-even
    with pytest.raises(UnitError):
        ev("min(ds.vout_nom, board.r_shunt)")


def test_names_collected_in_order():
    f = parse("ds.power_va / ds.vout_nom * (1 + ds.power_va / ds.power_va)")
    assert f.names == ("ds.power_va", "ds.vout_nom")


@pytest.mark.parametrize(
    "src",
    [
        "__import__('os')",
        "ds.vout_nom if 1 else 2",
        "[1, 2]",
        "ds.vout_nom ** board.g_amp",
        "lambda: 1",
        "'text'",
        "open('x')",
        "ds.power_va[0]",
        "True",
    ],
)
def test_forbidden_constructs(src):
    with pytest.raises(ExprError):
        parse(src)


def test_unknown_name():
    with pytest.raises(ExprError, match="unknown name"):
        ev("ds.nope * 2")


def test_division_by_zero():
    with pytest.raises(ExprError, match="division by zero"):
        ev("ds.vout_nom / 0")
