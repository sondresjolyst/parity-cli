import json
from dataclasses import replace

import yaml

from parity_cli import templates
from parity_cli.model import Kind


def test_dependabot_merges_ecosystems(config):
    files = templates.desired_files(["python", "node"], config)
    dependabot = next(f for f in files if f.kind is Kind.DEPENDABOT)
    doc = yaml.safe_load(dependabot.content)
    ecosystems = {u["package-ecosystem"] for u in doc["updates"]}
    assert ecosystems == {"github-actions", "pip", "npm"}
    assert doc["version"] == 2


def test_dependabot_carries_house_settings(config):
    files = templates.desired_files(["python"], config)
    doc = yaml.safe_load(next(f for f in files if f.kind is Kind.DEPENDABOT).content)
    pip = next(u for u in doc["updates"] if u["package-ecosystem"] == "pip")
    assert pip["schedule"] == {
        "interval": "weekly",
        "day": "sunday",
        "time": "03:00",
        "timezone": "Europe/Oslo",
    }
    assert pip["cooldown"] == {"default-days": 7}
    assert pip["commit-message"] == {"prefix": "deps(pip)"}


def test_codeowners_variable_substituted(config):
    files = templates.desired_files([], config)
    codeowners = next(f for f in files if f.kind is Kind.CODEOWNERS)
    assert codeowners.content.strip() == "* @sondresjolyst"


def test_team_mode_codeowners_defaults_owner_from_first_team(config):
    team_config = replace(
        config,
        owner="",
        discovery_mode="team",
        teams=["my-org/platform-team"],
        vars={},
    )

    files = templates.desired_files([], team_config)
    codeowners = next(f for f in files if f.kind is Kind.CODEOWNERS)
    assert codeowners.content.strip() == "* @my-org/platform-team"


def test_team_mode_codeowners_keeps_explicit_owner_var(config):
    team_config = replace(
        config,
        owner="",
        discovery_mode="team",
        teams=["my-org/platform-team"],
        vars={"owner": "@custom/team"},
    )

    files = templates.desired_files([], team_config)
    codeowners = next(f for f in files if f.kind is Kind.CODEOWNERS)
    assert codeowners.content.strip() == "* @custom/team"


def test_workflow_included(config):
    files = templates.desired_files([], config)
    paths = {f.path for f in files if f.kind is Kind.WORKFLOW}
    assert ".github/workflows/dependency-review.yml" in paths


def test_public_repo_gets_dependency_review(config):
    paths = {f.path for f in templates.desired_files([], config, private=False)}
    assert ".github/workflows/dependency-review.yml" in paths


def test_private_repo_skips_dependency_review_keeps_others(config):
    paths = {f.path for f in templates.desired_files([], config, private=True)}
    assert ".github/workflows/dependency-review.yml" not in paths
    assert ".github/workflows/dependabot-title.yml" in paths


def test_self_reference_workflow_skipped_in_host_repo(config):
    host = {f.path for f in templates.desired_files(
        [], config, full_name="sondresjolyst/garge")}
    other = {f.path for f in templates.desired_files(
        [], config, full_name="sondresjolyst/garge-app")}
    assert ".github/workflows/dependabot-title.yml" not in host
    assert ".github/workflows/dependabot-title.yml" in other


def test_cpp_has_no_pip_entry(config):
    files = templates.desired_files(["cpp"], config)
    doc = yaml.safe_load(next(f for f in files if f.kind is Kind.DEPENDABOT).content)
    ecosystems = {u["package-ecosystem"] for u in doc["updates"]}
    assert ecosystems == {"github-actions"}


_PRESET = "github>acme/renovate-config"


def _renovate(config, **overrides):
    return replace(
        config,
        dependency_manager="renovate",
        renovate_preset=_PRESET,
        **overrides,
    )


def test_dependabot_is_the_default_manager(config):
    default = replace(config, dependency_manager_repos={})
    kinds = {f.kind for f in templates.desired_files(["node"], default, repo="r")}
    assert Kind.DEPENDABOT in kinds
    assert Kind.RENOVATE not in kinds


def test_renovate_repo_gets_renovate_json_instead_of_dependabot(config):
    files = templates.desired_files(
        ["node"], _renovate(config, dependency_manager_repos={}), repo="r"
    )
    kinds = {f.kind for f in files}
    assert Kind.DEPENDABOT not in kinds
    renovate = next(f for f in files if f.kind is Kind.RENOVATE)
    assert renovate.path == "renovate.json"
    assert json.loads(renovate.content)["extends"] == [_PRESET]


def test_repo_override_picks_manager_per_repo(config):
    mixed = replace(
        config,
        dependency_manager="dependabot",
        dependency_manager_repos={"moved": "renovate"},
        renovate_preset=_PRESET,
    )
    moved = {f.kind for f in templates.desired_files(["node"], mixed, repo="moved")}
    other = {f.kind for f in templates.desired_files(["node"], mixed, repo="other")}
    assert Kind.RENOVATE in moved and Kind.DEPENDABOT not in moved
    assert Kind.DEPENDABOT in other and Kind.RENOVATE not in other


def test_override_back_to_dependabot_when_default_is_renovate(config):
    mixed = _renovate(config, dependency_manager_repos={"stay": "dependabot"})
    stay = {f.kind for f in templates.desired_files(["node"], mixed, repo="stay")}
    assert Kind.DEPENDABOT in stay and Kind.RENOVATE not in stay


def test_codeowners_stays_for_renovate_unless_removal_is_enabled(config):
    kept = templates.desired_files(
        ["node"],
        _renovate(config, dependency_manager_repos={}, renovate_remove_codeowners=False),
        repo="r",
    )
    assert any(f.kind is Kind.CODEOWNERS for f in kept)
    removed = templates.desired_files(
        ["node"],
        _renovate(config, dependency_manager_repos={}, renovate_remove_codeowners=True),
        repo="r",
    )
    assert not any(f.kind is Kind.CODEOWNERS for f in removed)


def test_removable_manager_files_for_renovate(config):
    assert templates.removable_manager_files(
        _renovate(config, dependency_manager_repos={}, renovate_remove_codeowners=False),
        "r",
    ) == [(templates.DEPENDABOT_PATH, Kind.RENOVATE)]
    assert templates.removable_manager_files(
        _renovate(config, dependency_manager_repos={}, renovate_remove_codeowners=True),
        "r",
    ) == [
        (templates.DEPENDABOT_PATH, Kind.RENOVATE),
        (templates.CODEOWNERS_PATH, Kind.CODEOWNERS),
    ]


def test_dependabot_repo_never_removes_anything(config):
    dependabot = replace(
        config,
        dependency_manager="dependabot",
        dependency_manager_repos={},
        renovate_remove_codeowners=True,
    )
    assert templates.removable_manager_files(dependabot, "r") == []


def test_workflow_manager_filter():
    value = {"languages": ["all"], "manager": "dependabot"}
    assert (
        templates.classify_workflow(value, [], False, "r", manager="dependabot")
        == "desired"
    )
    assert (
        templates.classify_workflow(value, [], False, "r", manager="renovate")
        == "removable"
    )


def test_workflow_without_manager_applies_to_both():
    for manager in ("dependabot", "renovate"):
        assert (
            templates.classify_workflow(["all"], [], False, "r", manager=manager)
            == "desired"
        )


def test_dependabot_title_workflow_follows_the_manager(config):
    title = ".github/workflows/dependabot-title.yml"
    dependabot = replace(config, dependency_manager_repos={})
    files = templates.desired_files(["node"], dependabot, repo="r")
    assert any(f.path == title for f in files)
    renovate = _renovate(config, dependency_manager_repos={})
    files = templates.desired_files(["node"], renovate, repo="r")
    assert not any(f.path == title for f in files)
    assert title in templates.removable_workflow_paths(
        ["node"], renovate, False, "r", "o/r"
    )


def test_node_repo_gets_release_age_npmrc(config):
    files = templates.desired_files(["node"], config, repo="r")
    npmrc = next(f for f in files if f.path == ".npmrc")
    assert "min-release-age=7" in npmrc.content
    assert not any(
        f.path == ".npmrc" for f in templates.desired_files(["python"], config, repo="r")
    )


def test_release_review_workflow_only_on_renovate_repos(config):
    path = ".github/workflows/release-review.yml"
    moved = _renovate(config, dependency_manager_repos={})
    stay = replace(config, dependency_manager="dependabot", dependency_manager_repos={})
    wanted = next(f for f in templates.desired_files([], moved, repo="r") if f.path == path)
    assert 'gh pr edit "$number" --add-reviewer "$REVIEWERS"' in wanted.content
    assert "${{ github.token }}" in wanted.content
    assert not any(f.path == path for f in templates.desired_files([], stay, repo="r"))


def test_release_review_workflow_stays_in_its_source_repo(config):
    moved = replace(config, dependency_manager="dependabot", dependency_manager_repos={})
    assert ".github/workflows/release-review.yml" not in templates.removable_workflow_paths(
        [], moved, False, "parity-cli", "o/parity-cli"
    )


def test_release_review_workflow_is_valid_yaml(config):
    moved = _renovate(config, dependency_manager_repos={})
    wanted = next(
        f for f in templates.desired_files([], moved, repo="r")
        if f.path == ".github/workflows/release-review.yml"
    )
    doc = yaml.safe_load(wanted.content)
    run = doc["jobs"]["request"]["steps"][0]["run"]
    assert "set -euo pipefail" in run
    assert ".reviews | length" in run


def _review_env(config, **overrides):
    moved = _renovate(config, dependency_manager_repos={}, **overrides)
    wanted = next(
        f for f in templates.desired_files([], moved, repo="r")
        if f.path == ".github/workflows/release-review.yml"
    )
    job = yaml.safe_load(wanted.content)["jobs"]["request"]
    return job["steps"][0]["env"]["REVIEWERS"], job["if"]


def test_release_reviewers_come_from_vars(config):
    reviewers, condition = _review_env(
        config, vars={"owner": "@o", "release_reviewers": "a,org/team"}
    )
    assert reviewers == "a,org/team"
    assert "$" not in condition.replace("'$'", "")


def test_release_reviewers_default_to_the_owner(config):
    reviewers, _ = _review_env(config, vars={"owner": "@org/team"})
    assert reviewers == "org/team"


def test_repo_vars_override_release_reviewers_for_that_repo_only(config):
    reviewers, _ = _review_env(
        config,
        vars={"owner": "@o", "release_reviewers": "a"},
        repo_vars={"r": {"release_reviewers": "b"}},
    )
    assert reviewers == "b"
    other, _ = _review_env(
        config,
        vars={"owner": "@o", "release_reviewers": "a"},
        repo_vars={"other": {"release_reviewers": "b"}},
    )
    assert other == "a"


def test_unfilled_source_workflow_cannot_run():
    source = (templates.Path(__file__).parents[1] / ".github/workflows/release-review.yml")
    job = yaml.safe_load(source.read_text(encoding="utf-8"))["jobs"]["request"]
    assert job["if"] == "!contains('${release_reviewers}', '$')"
