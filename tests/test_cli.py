import pytest
from typer.testing import CliRunner

from mdflow.cli import app

runner = CliRunner()


@pytest.fixture(autouse=True)
def _isolated_cache_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("MDFLOW_CACHE_DIR", str(tmp_path / "cache"))


def test_convert_file_to_stdout(tmp_path):
    p = tmp_path / "a.txt"
    p.write_text("hello cli")
    r = runner.invoke(app, ["convert", str(p)])
    assert r.exit_code == 0
    assert "hello cli" in r.stdout


def test_convert_file_to_output(tmp_path):
    p = tmp_path / "a.txt"
    p.write_text("write me")
    out = tmp_path / "out.md"
    r = runner.invoke(app, ["convert", str(p), "-o", str(out)])
    assert r.exit_code == 0
    assert out.read_text() == "write me"


def test_convert_requires_exactly_one_input(tmp_path):
    assert runner.invoke(app, ["convert"]).exit_code != 0
    p = tmp_path / "a.txt"
    p.write_text("x")
    assert runner.invoke(app, ["convert", str(p), "--url", "https://x/y"]).exit_code != 0


def test_convert_missing_file():
    assert runner.invoke(app, ["convert", "/no/such/file.txt"]).exit_code != 0


def test_serve_invokes_uvicorn(monkeypatch):
    calls = {}
    import mdflow.cli as cli

    def fake_run(app_obj, host, port):
        calls["host"] = host
        calls["port"] = port

    monkeypatch.setattr(cli.uvicorn, "run", fake_run)
    r = runner.invoke(app, ["serve", "--host", "0.0.0.0", "--port", "9000"])
    assert r.exit_code == 0
    assert calls == {"host": "0.0.0.0", "port": 9000}


def test_help_lists_commands():
    out = runner.invoke(app, ["--help"]).stdout
    assert "convert" in out and "serve" in out
