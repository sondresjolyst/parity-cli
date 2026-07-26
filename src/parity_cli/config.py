"""Load parity config and template mappings."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class Config:
    owner: str
    templates_dir: Path
    workflows_dir: Path
    language_threshold: float = 0.10
    include_archived: bool = False
    include_forks: bool = False
    branch_name: str = "parity/sync-standards"
    # GitHub language name -> template directory under templates/
    language_map: dict[str, str] = field(default_factory=dict)
    # workflow filename -> languages it applies to (["all"] for every repo)
    workflows: dict[str, list[str]] = field(default_factory=dict)
    # placeholders substituted into templates, e.g. {"owner": "@sondresjolyst"}
    vars: dict[str, str] = field(default_factory=dict)
    repos_include: list[str] = field(default_factory=list)
    repos_exclude: list[str] = field(default_factory=list)


DEFAULT_LANGUAGE_MAP = {
    "Python": "python",
    "JavaScript": "node",
    "TypeScript": "node",
    "C#": "dotnet",
    "C++": "cpp",
    "C": "cpp",
    "Go": "go",
    "Rust": "rust",
    "Java": "java",
    "Ruby": "ruby",
    "PHP": "php",
    "Dockerfile": "docker",
}


def load(path: str | Path) -> Config:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Config not found: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}

    def _resolve(value: str) -> Path:
        p = Path(value)
        return p if p.is_absolute() else (path.parent / p).resolve()

    lang_map = dict(DEFAULT_LANGUAGE_MAP)
    lang_map.update(data.get("language_map", {}))
    return Config(
        owner=data["owner"],
        templates_dir=_resolve(data.get("templates_dir", "templates")),
        workflows_dir=_resolve(data.get("workflows_dir", ".github/workflows")),
        language_threshold=float(data.get("language_threshold", 0.10)),
        include_archived=bool(data.get("include_archived", False)),
        include_forks=bool(data.get("include_forks", False)),
        branch_name=data.get("branch_name", Config.branch_name),
        language_map=lang_map,
        workflows=data.get("workflows", {"dependency-review.yml": ["all"]}),
        vars=data.get("vars", {}),
        repos_include=data.get("repos_include", []),
        repos_exclude=data.get("repos_exclude", []),
    )
