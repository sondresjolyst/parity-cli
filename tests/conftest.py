from pathlib import Path

import pytest

from parity_cli import config as config_mod
from parity_cli.config import Config

ROOT = Path(__file__).parents[1]


@pytest.fixture
def config() -> Config:
    return config_mod.load(ROOT / "parity.yml")
