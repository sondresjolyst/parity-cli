from dataclasses import replace

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


def test_dependabot_unquoted_sexagesimal_time_is_drift():
    desired = "schedule:\n  time: '03:00'\n"
    current = "schedule:\n  time: 03:00\n"
    assert _cmp(desired, current) is Status.DRIFT


def test_dependabot_quoted_time_matches_quoted_time():
    desired = "schedule:\n  time: '03:00'\n"
    current = "schedule:\n  time: \"03:00\"\n"
    assert _cmp(desired, current) is Status.MATCH


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


_PRESET = "github>acme/renovate-config"
_RENOVATE = '{"extends": ["github>acme/renovate-config"]}'


def test_renovate_extending_the_preset_matches():
    assert _cmp(_RENOVATE, _RENOVATE, Kind.RENOVATE) is Status.MATCH


def test_renovate_repo_rules_are_kept_as_a_match():
    current = (
        '{"extends": ["github>acme/renovate-config"],'
        ' "packageRules": [{"matchPackageNames": ["react"], "enabled": false}]}'
    )
    assert _cmp(_RENOVATE, current, Kind.RENOVATE) is Status.MATCH


def test_renovate_without_the_preset_drifts():
    assert _cmp(_RENOVATE, '{"extends": ["config:base"]}', Kind.RENOVATE) is Status.DRIFT


def test_renovate_invalid_json_drifts():
    assert _cmp(_RENOVATE, "{not json", Kind.RENOVATE) is Status.DRIFT


def test_renovate_non_object_json_drifts():
    assert _cmp(_RENOVATE, "[]", Kind.RENOVATE) is Status.DRIFT


def test_scan_marks_old_manager_files_for_removal(config, monkeypatch):
    moved = replace(
        config,
        dependency_manager="renovate",
        dependency_manager_repos={},
        renovate_preset=_PRESET,
        renovate_remove_codeowners=True,
    )
    existing = {
        ".github/dependabot.yml": "version: 2\n",
        ".github/CODEOWNERS": "* @x\n",
    }
    monkeypatch.setattr(gh, "languages", lambda *a, **k: {"TypeScript": 1})
    monkeypatch.setattr(gh, "has_workflow_files", lambda *a, **k: True)
    monkeypatch.setattr(gh, "get_file", lambda _r, path, _b: existing.get(path))
    result = drift.scan_repo(_REPO, moved)
    by_path = {f.path: f for f in result.files}
    assert by_path["renovate.json"].status is Status.MISSING
    assert by_path[".github/dependabot.yml"].status is Status.EXTRA
    assert by_path[".github/CODEOWNERS"].status is Status.EXTRA


def test_scan_skips_removal_when_old_files_are_gone(config, monkeypatch):
    moved = replace(
        config,
        dependency_manager="renovate",
        dependency_manager_repos={},
        renovate_preset=_PRESET,
        renovate_remove_codeowners=True,
    )
    monkeypatch.setattr(gh, "languages", lambda *a, **k: {"TypeScript": 1})
    monkeypatch.setattr(gh, "has_workflow_files", lambda *a, **k: True)
    monkeypatch.setattr(gh, "get_file", lambda *a, **k: None)
    result = drift.scan_repo(_REPO, moved)
    assert not any(f.status is Status.EXTRA for f in result.files)


def test_scan_leaves_renovate_json_alone_on_a_dependabot_repo(config, monkeypatch):
    stay = replace(config, dependency_manager_repos={})
    monkeypatch.setattr(gh, "languages", lambda *a, **k: {"TypeScript": 1})
    monkeypatch.setattr(gh, "has_workflow_files", lambda *a, **k: True)
    monkeypatch.setattr(
        gh, "get_file", lambda _r, path, _b: "{}" if path == "renovate.json" else None
    )
    result = drift.scan_repo(_REPO, stay)
    assert not any(f.path == "renovate.json" for f in result.files)
