"""Load parity config and template mappings."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from . import gh


@dataclass
class Config:
    templates_dir: Path
    workflows_dir: Path
    owner: str = ""
    discovery_mode: str = "owner"
    teams: list[str] = field(default_factory=list)
    # Minimum team permission a repo must grant to be included when
    # discovery_mode is "team": "push" (needed for `apply`) or "admin"
    # (also needed for `parity settings --apply`).
    team_permission: str = "push"
    language_threshold: float = 0.10
    include_archived: bool = False
    include_forks: bool = False
    branch_name: str = "parity/sync-standards"
    draft_pr: bool = True
    # GitHub language name -> template directory under templates/
    language_map: dict[str, str] = field(default_factory=dict)
    # workflow filename -> languages it applies to (["all"] for every repo)
    workflows: dict[str, list[str]] = field(default_factory=dict)
    # managed repo settings key -> desired value
    settings: dict[str, object] = field(default_factory=dict)
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


def discover_repos(
    config: Config, *, include_archived: bool, include_forks: bool
) -> list[gh.Repo]:
    if config.discovery_mode == "team":
        return gh.list_repos_for_teams(
            config.teams,
            min_permission=config.team_permission,
            include_archived=include_archived,
            include_forks=include_forks,
        )
    return gh.list_repos(
        config.owner,
        include_archived=include_archived,
        include_forks=include_forks,
    )


def load(path: str | Path) -> Config:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Config not found: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}

    def _resolve(value: str) -> Path:
        p = Path(value)
        return p if p.is_absolute() else (path.parent / p).resolve()

    discovery_mode = str(data.get("discovery_mode", "owner"))
    if discovery_mode not in {"owner", "team"}:
        raise ValueError(
            f"Unsupported discovery_mode {discovery_mode!r} in {path}. "
            "Expected 'owner' or 'team'."
        )

    owner = str(data.get("owner", "") or "")
    teams = list(data.get("teams", []) or [])
    team_permission = str(data.get("team_permission", "push"))
    if team_permission not in gh.PERMISSION_LEVELS:
        raise ValueError(
            f"Unsupported team_permission {team_permission!r} in {path}. "
            f"Expected one of {gh.PERMISSION_LEVELS}."
        )
    if discovery_mode == "owner" and not owner:
        raise ValueError(
            "discovery_mode is 'owner' but no owner is configured in parity.yml"
        )
    if discovery_mode == "team" and not teams:
        raise ValueError(
            "discovery_mode is 'team' but no teams are configured in parity.yml"
        )

    lang_map = dict(DEFAULT_LANGUAGE_MAP)
    lang_map.update(data.get("language_map", {}))
    return Config(
        templates_dir=_resolve(data.get("templates_dir", "templates")),
        workflows_dir=_resolve(data.get("workflows_dir", ".github/workflows")),
        owner=owner,
        discovery_mode=discovery_mode,
        teams=teams,
        team_permission=team_permission,
        language_threshold=float(data.get("language_threshold", 0.10)),
        include_archived=bool(data.get("include_archived", False)),
        include_forks=bool(data.get("include_forks", False)),
        branch_name=data.get("branch_name", Config.branch_name),
        draft_pr=bool(data.get("draft_pr", Config.draft_pr)),
        language_map=lang_map,
        workflows=data.get("workflows", {"dependency-review.yml": ["all"]}),
        settings=data.get("settings", {}),
        vars=data.get("vars", {}),
        repos_include=data.get("repos_include", []),
        repos_exclude=data.get("repos_exclude", []),
    )
