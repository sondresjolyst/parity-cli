from pathlib import Path

import pytest

from parity_cli import config as config_mod

FIXTURES = Path(__file__).with_name("fixtures")


def test_load_legacy_config_defaults_to_owner_mode():
    cfg = config_mod.load(FIXTURES / "legacy-parity.yml")

    assert cfg.discovery_mode == "owner"
    assert cfg.owner == "octocat"
    assert cfg.teams == []


def test_team_mode_requires_teams():
    with pytest.raises(
        ValueError,
        match="discovery_mode is 'team' but no teams are configured in parity.yml",
    ):
        config_mod.load(FIXTURES / "team-missing-teams-parity.yml")


def test_owner_mode_requires_owner():
    with pytest.raises(
        ValueError,
        match="discovery_mode is 'owner' but no owner is configured in parity.yml",
    ):
        config_mod.load(FIXTURES / "owner-missing-owner-parity.yml")


def test_team_mode_allows_owner_to_be_omitted():
    cfg = config_mod.load(FIXTURES / "team-parity.yml")

    assert cfg.discovery_mode == "team"
    assert cfg.owner == ""
    assert cfg.teams == ["my-org/platform-team"]


def _write(tmp_path, text):
    path = tmp_path / "parity.yml"
    path.write_text(text, encoding="utf-8")
    return path


def test_dependency_manager_defaults_to_dependabot(tmp_path):
    cfg = config_mod.load(_write(tmp_path, "owner: me\n"))
    assert cfg.dependency_manager == "dependabot"
    assert cfg.manager_for("any") == "dependabot"
    assert cfg.renovate_remove_codeowners is False


def test_manager_for_uses_repo_override(tmp_path):
    cfg = config_mod.load(_write(
        tmp_path,
        "owner: me\n"
        "renovate_preset: github>me/config\n"
        "dependency_manager_repos:\n  moved: renovate\n",
    ))
    assert cfg.manager_for("moved") == "renovate"
    assert cfg.manager_for("other") == "dependabot"


def test_unknown_manager_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="dependency_manager"):
        config_mod.load(_write(tmp_path, "owner: me\ndependency_manager: nope\n"))


def test_unknown_repo_manager_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="dependency_manager"):
        config_mod.load(_write(
            tmp_path, "owner: me\ndependency_manager_repos:\n  r: nope\n"
        ))


def test_renovate_requires_a_preset(tmp_path):
    with pytest.raises(ValueError, match="renovate_preset"):
        config_mod.load(_write(tmp_path, "owner: me\ndependency_manager: renovate\n"))
    with pytest.raises(ValueError, match="renovate_preset"):
        config_mod.load(_write(
            tmp_path, "owner: me\ndependency_manager_repos:\n  r: renovate\n"
        ))
