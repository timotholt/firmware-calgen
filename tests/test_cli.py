import pytest

from calgen import __version__
from calgen.cli import main


def test_no_command_prints_help(capsys):
    assert main([]) == 0
    assert "calgen" in capsys.readouterr().out


def test_version(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert __version__ in capsys.readouterr().out
