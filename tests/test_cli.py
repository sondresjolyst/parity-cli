import io

from rich.console import Console

from parity_cli import cli
from parity_cli.model import RepoResult


def test_output_survives_a_non_utf8_console():
    raw = io.BytesIO()
    stream = io.TextIOWrapper(raw, encoding="cp1252")
    cli._use_utf8_output(stream)
    stream.write("\u2713")
    stream.flush()
    assert raw.getvalue() == "\u2713".encode("utf-8")


def _summary_text(monkeypatch, results):
    out = io.StringIO()
    monkeypatch.setattr(cli, "console", Console(file=out, width=200))
    cli._summary(results)
    return out.getvalue()


def test_summary_counts_failed_repos(monkeypatch):
    failed = RepoResult("r", "o/r", "main", [], error="rate limit")
    assert "1 failed" in _summary_text(monkeypatch, [failed])


def test_summary_stays_quiet_without_failures(monkeypatch):
    fine = RepoResult("r", "o/r", "main", [])
    assert "failed" not in _summary_text(monkeypatch, [fine])
