from pathlib import Path

import pytest

from parity_cli import config as config_mod
from parity_cli import gh
from parity_cli.config import Config

ROOT = Path(__file__).parents[1]


@pytest.fixture
def config() -> Config:
    return config_mod.load(ROOT / "tests/fixtures/parity.yml")


@pytest.fixture(autouse=True)
def no_tree_lookup(monkeypatch):
    """Tests stub single files unless they opt in to the tree lookup."""
    monkeypatch.setattr(gh, "repo_paths", lambda *a, **k: None)
