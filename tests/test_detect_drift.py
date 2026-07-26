from parity_cli import drift, gh
from parity_cli.detect import template_dirs
from parity_cli.model import DesiredFile, Kind, Status

_REPO = gh.Repo("r", "o/r", "main", False, False, False)


def test_python_repo_with_uv_lock_uses_uv(monkeypatch):
    monkeypatch.setattr(gh, "get_file", lambda *a, **k: "lock contents")
    assert drift._resolve_python_tool(_REPO, ["python"]) == ["uv"]


def test_python_repo_without_uv_lock_stays_pip(monkeypatch):
    monkeypatch.setattr(gh, "get_file", lambda *a, **k: None)
    assert drift._resolve_python_tool(_REPO, ["python"]) == ["python"]


def test_non_python_untouched(monkeypatch):
    monkeypatch.setattr(gh, "get_file", lambda *a, **k: "lock")
    assert drift._resolve_python_tool(_REPO, ["node"]) == ["node"]


def test_detect_above_threshold(config):
    langs = {"Python": 8000, "TypeScript": 2000, "Shell": 50}
    dirs = template_dirs(langs, config)
    assert dirs == ["python", "node"]


def test_detect_dedups_js_and_ts(config):
    langs = {"JavaScript": 5000, "TypeScript": 5000}
    assert template_dirs(langs, config) == ["node"]


def test_detect_drops_below_threshold(config):
    langs = {"Python": 9500, "C++": 500}
    assert template_dirs(langs, config) == ["python"]


def _cmp(desired_text, current_text, kind=Kind.DEPENDABOT):
    d = DesiredFile(".github/x.yml", kind, desired_text)
    return drift._compare(d, current_text).status


def test_missing_when_absent():
    assert _cmp("a: 1", None) is Status.MISSING


def test_yaml_semantic_match_ignores_formatting():
    desired = "version: 2\nupdates: []\n"
    current = "version:   2\nupdates:  []"
    assert _cmp(desired, current) is Status.MATCH


def test_drift_on_real_difference():
    assert _cmp("version: 2\nupdates: []", "version: 2\nupdates: [1]") is Status.DRIFT


def test_codeowners_trailing_newline_matches():
    assert _cmp("* @tester\n", "* @tester", Kind.CODEOWNERS) is Status.MATCH


_WF_TEMPLATE = """\
name: CI
on: [push]
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa # v7.0.0
"""


def test_workflow_ignores_bumped_action_sha():
    bumped = _WF_TEMPLATE.replace(
        "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa # v7.0.0",
        "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb # v7.1.0",
    )
    assert _cmp(_WF_TEMPLATE, bumped, Kind.WORKFLOW) is Status.MATCH


def test_workflow_flags_structural_change():
    changed = _WF_TEMPLATE.replace("on: [push]", "on: [pull_request]")
    assert _cmp(_WF_TEMPLATE, changed, Kind.WORKFLOW) is Status.DRIFT
