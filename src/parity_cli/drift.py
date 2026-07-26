"""Compare desired files against what each repo currently has."""

from __future__ import annotations

import re
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed

import yaml

from . import gh
from .config import Config
from .detect import template_dirs
from .model import DesiredFile, FileResult, Kind, RepoResult, Status
from .templates import desired_files, removable_workflow_paths


_USES = re.compile(r"^(\s*(?:-\s*)?uses:\s*\S+?)@\S+.*$")


def _normalize(text: str) -> str:
    lines = [line.rstrip() for line in text.replace("\r\n", "\n").split("\n")]
    while lines and not lines[-1]:
        lines.pop()
    return "\n".join(lines)


def _strip_action_refs(text: str) -> str:
    return "\n".join(
        m.group(1) if (m := _USES.match(line)) else line
        for line in text.replace("\r\n", "\n").split("\n")
    )


def _equal(desired: DesiredFile, current: str) -> bool:
    if desired.kind is Kind.DEPENDABOT:
        try:
            return yaml.safe_load(desired.content) == yaml.safe_load(current)
        except yaml.YAMLError:
            pass
    if desired.kind is Kind.WORKFLOW:
        want, have = _strip_action_refs(desired.content), _strip_action_refs(current)
        try:
            return yaml.safe_load(want) == yaml.safe_load(have)
        except yaml.YAMLError:
            return _normalize(want) == _normalize(have)
    return _normalize(desired.content) == _normalize(current)


def _compare(desired: DesiredFile, current: str | None) -> FileResult:
    if current is None:
        status = Status.MISSING
    elif _equal(desired, current):
        status = Status.MATCH
    else:
        status = Status.DRIFT
    return FileResult(desired.path, desired.kind, status, desired.content, current)


def _resolve_python_tool(repo: gh.Repo, dirs: list[str]) -> list[str]:
    if "python" not in dirs:
        return dirs
    if gh.get_file(repo.full_name, "uv.lock", repo.default_branch) is None:
        return dirs
    return ["uv" if d == "python" else d for d in dirs]


def scan_repo(repo: gh.Repo, config: Config) -> RepoResult:
    result = RepoResult(
        repo=repo.name,
        full_name=repo.full_name,
        default_branch=repo.default_branch,
        languages=[],
        private=repo.private,
    )
    try:
        langs = gh.languages(repo.full_name)
        dirs = template_dirs(langs, config)
        dirs = _resolve_python_tool(repo, dirs)
        result.languages = dirs
        desired = desired_files(
            dirs, config, private=repo.private, repo=repo.name,
            full_name=repo.full_name,
        )
        for want in desired:
            current = gh.get_file(repo.full_name, want.path, repo.default_branch)
            result.files.append(_compare(want, current))
        for path in removable_workflow_paths(
            dirs, config, repo.private, repo.name, repo.full_name
        ):
            current = gh.get_file(repo.full_name, path, repo.default_branch)
            if current is not None:
                result.files.append(
                    FileResult(path, Kind.WORKFLOW, Status.EXTRA, "", current)
                )
    except gh.GhError as exc:
        result.error = str(exc)
    return result


def _selected(repos: list[gh.Repo], config: Config) -> list[gh.Repo]:
    out = []
    for r in repos:
        if config.repos_include and r.name not in config.repos_include:
            continue
        if r.name in config.repos_exclude:
            continue
        out.append(r)
    return out


def scan(
    config: Config,
    *,
    workers: int = 8,
    on_start: Callable[[int], None] | None = None,
    on_progress: Callable[[], None] | None = None,
) -> list[RepoResult]:
    repos = gh.list_repos(
        config.owner,
        include_archived=config.include_archived,
        include_forks=config.include_forks,
    )
    repos = _selected(repos, config)
    if on_start:
        on_start(len(repos))
    results: list[RepoResult] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(scan_repo, r, config) for r in repos]
        for future in as_completed(futures):
            results.append(future.result())
            if on_progress:
                on_progress()
    return results
