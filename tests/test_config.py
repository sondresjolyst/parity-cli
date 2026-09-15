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
