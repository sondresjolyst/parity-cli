"""Assemble the desired file set for a repo from templates."""

from __future__ import annotations

import re
from pathlib import Path
from string import Template

import yaml

from .config import Config
from .model import DesiredFile, Kind

BASE_DIR = "_base"
ACTIONS_DIR = "_actions"
DEPENDABOT_PATH = ".github/dependabot.yml"
CODEOWNERS_PATH = ".github/CODEOWNERS"
WORKFLOWS_PREFIX = ".github/workflows"
DEPENDABOT_FRAGMENT = "dependabot.fragment.yml"


def _subst(text: str, variables: dict[str, str]) -> str:
    return Template(text).safe_substitute(variables)


def _read(path: Path, variables: dict[str, str]) -> str:
    return _subst(path.read_text(encoding="utf-8"), variables)


def _dependabot(dirs: list[str], config: Config) -> DesiredFile | None:
    updates: list[dict] = []
    search = [ACTIONS_DIR, *dirs]
    for name in search:
        fragment = config.templates_dir / name / DEPENDABOT_FRAGMENT
        if not fragment.exists():
            continue
        parsed = yaml.safe_load(_read(fragment, config.vars)) or []
        if isinstance(parsed, dict):
            parsed = parsed.get("updates", [])
        updates.extend(parsed)
    if not updates:
        return None
    doc = {"version": 2, "updates": updates}
    content = yaml.safe_dump(doc, sort_keys=False, default_flow_style=False)
    return DesiredFile(DEPENDABOT_PATH, Kind.DEPENDABOT, content)


def _codeowners(config: Config) -> DesiredFile | None:
    path = config.templates_dir / BASE_DIR / "CODEOWNERS"
    if not path.exists():
        return None
    return DesiredFile(CODEOWNERS_PATH, Kind.CODEOWNERS, _read(path, config.vars))


def _wf_spec(value) -> tuple[list[str], str, list[str]]:
    if isinstance(value, dict):
        return (
            value.get("languages", ["all"]),
            value.get("visibility", "all"),
            value.get("exclude", []),
        )
    return value, "all", []


def _visibility_ok(visibility: str, private: bool) -> bool:
    if visibility == "public":
        return not private
    if visibility == "private":
        return private
    return True


def classify_workflow(value, dirs: list[str], private: bool, repo: str) -> str:
    """Return 'desired', 'removable', or 'ignore' for a workflow in a repo."""
    langs, visibility, exclude = _wf_spec(value)
    if repo in exclude:
        return "ignore"
    lang_ok = "all" in langs or any(lang in dirs for lang in langs)
    if lang_ok and _visibility_ok(visibility, private):
        return "desired"
    return "removable"


def removable_workflow_paths(
    dirs: list[str], config: Config, private: bool, repo: str, full_name: str
) -> list[str]:
    paths = []
    for name, value in config.workflows.items():
        if classify_workflow(value, dirs, private, repo) != "removable":
            continue
        src = config.workflows_dir / name
        if src.is_file() and references_repo(_read(src, config.vars), full_name):
            continue
        paths.append(f"{WORKFLOWS_PREFIX}/{name}")
    return paths


def references_repo(content: str, full_name: str) -> bool:
    """True if a workflow calls a reusable workflow hosted in full_name."""
    if not full_name:
        return False
    return bool(re.search(rf"uses:\s*{re.escape(full_name)}/", content))


def _workflows(
    dirs: list[str], config: Config, private: bool, repo: str, full_name: str
) -> list[DesiredFile]:
    found: dict[str, DesiredFile] = {}
    for filename, value in config.workflows.items():
        if classify_workflow(value, dirs, private, repo) != "desired":
            continue
        src = config.workflows_dir / filename
        if not src.is_file():
            continue
        content = _read(src, config.vars)
        if references_repo(content, full_name):
            continue
        repo_path = f"{WORKFLOWS_PREFIX}/{filename}"
        found[repo_path] = DesiredFile(repo_path, Kind.WORKFLOW, content)
    return list(found.values())


def _generic_files(dirs: list[str], config: Config) -> list[DesiredFile]:
    found: dict[str, DesiredFile] = {}
    for name in [BASE_DIR, ACTIONS_DIR, *dirs]:
        root = config.templates_dir / name / "files"
        if not root.is_dir():
            continue
        for src in sorted(root.rglob("*")):
            if not src.is_file():
                continue
            repo_path = src.relative_to(root).as_posix()
            found[repo_path] = DesiredFile(
                repo_path, Kind.FILE, _read(src, config.vars)
            )
    return list(found.values())


def desired_files(
    dirs: list[str], config: Config, *,
    private: bool = False, repo: str = "", full_name: str = "",
) -> list[DesiredFile]:
    files: list[DesiredFile] = []
    dependabot = _dependabot(dirs, config)
    if dependabot:
        files.append(dependabot)
    codeowners = _codeowners(config)
    if codeowners:
        files.append(codeowners)
    files.extend(_workflows(dirs, config, private, repo, full_name))
    files.extend(_generic_files(dirs, config))
    return files
