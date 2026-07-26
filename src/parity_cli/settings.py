"""Audit and fix repo-level GitHub settings across the fleet."""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field

from . import gh
from .config import Config

REPO_FIELDS = {
    "delete_branch_on_merge",
    "squash_merge_commit_title",
    "squash_merge_commit_message",
    "has_wiki",
    "allow_update_branch",
}
ACTIONS_FIELDS = {
    "actions_default_workflow_permissions": "default_workflow_permissions",
    "actions_can_approve_pull_request_reviews": "can_approve_pull_request_reviews",
}
SECURITY_FIELDS = {"dependabot_alerts", "dependabot_security_updates"}


@dataclass
class SettingDrift:
    key: str
    current: object
    desired: object


@dataclass
class RepoSettings:
    repo: str
    full_name: str
    drift: list[SettingDrift] = field(default_factory=list)
    error: str | None = None


def _current(full_name: str, keys: set[str]) -> dict:
    cur: dict[str, object] = {}
    if keys & REPO_FIELDS:
        repo = gh.get_repo(full_name)
        for key in keys & REPO_FIELDS:
            cur[key] = repo.get(key)
    if keys & set(ACTIONS_FIELDS):
        perms = gh.workflow_permissions(full_name)
        for key, api_key in ACTIONS_FIELDS.items():
            if key in keys:
                cur[key] = perms.get(api_key)
    if "dependabot_alerts" in keys:
        cur["dependabot_alerts"] = gh.vulnerability_alerts_enabled(full_name)
    if "dependabot_security_updates" in keys:
        cur["dependabot_security_updates"] = gh.automated_security_fixes_enabled(full_name)
    return cur


def scan_repo_settings(repo: gh.Repo, config: Config) -> RepoSettings:
    result = RepoSettings(repo.name, repo.full_name)
    if not config.settings:
        return result
    try:
        current = _current(repo.full_name, set(config.settings))
        result.drift = [
            SettingDrift(key, current.get(key), desired)
            for key, desired in config.settings.items()
            if current.get(key) != desired
        ]
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


def scan_settings(
    config: Config,
    *,
    workers: int = 8,
    on_start: Callable[[int], None] | None = None,
    on_progress: Callable[[], None] | None = None,
) -> list[RepoSettings]:
    repos = _selected(
        gh.list_repos(
            config.owner,
            include_archived=config.include_archived,
            include_forks=config.include_forks,
        ),
        config,
    )
    if on_start:
        on_start(len(repos))
    results: list[RepoSettings] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(scan_repo_settings, r, config) for r in repos]
        for future in as_completed(futures):
            results.append(future.result())
            if on_progress:
                on_progress()
    return results


def apply_drifts(full_name: str, drifts: list[SettingDrift], config: Config) -> None:
    keys = {d.key for d in drifts}
    repo_patch = {d.key: d.desired for d in drifts if d.key in REPO_FIELDS}
    if repo_patch:
        gh.patch_repo(full_name, repo_patch)
    if keys & set(ACTIONS_FIELDS):
        current = gh.workflow_permissions(full_name)
        default = (
            config.settings["actions_default_workflow_permissions"]
            if "actions_default_workflow_permissions" in keys
            else current.get("default_workflow_permissions", "read")
        )
        approve = (
            config.settings["actions_can_approve_pull_request_reviews"]
            if "actions_can_approve_pull_request_reviews" in keys
            else current.get("can_approve_pull_request_reviews", False)
        )
        gh.set_workflow_permissions(full_name, str(default), bool(approve))
    if "dependabot_alerts" in keys:
        gh.set_vulnerability_alerts(
            full_name, bool(config.settings["dependabot_alerts"])
        )
    if "dependabot_security_updates" in keys:
        gh.set_automated_security_fixes(
            full_name, bool(config.settings["dependabot_security_updates"])
        )


def apply_settings(result: RepoSettings, config: Config) -> None:
    apply_drifts(result.full_name, result.drift, config)


@dataclass
class ApplyResult:
    repo: str
    ok: bool
    error: str | None = None


def apply_many(
    targets: list[tuple[str, str, list[SettingDrift]]],
    config: Config,
    *,
    workers: int = 8,
    on_result: Callable[[ApplyResult], None] | None = None,
) -> list[ApplyResult]:
    def run(target: tuple[str, str, list[SettingDrift]]) -> ApplyResult:
        full_name, repo, drifts = target
        try:
            apply_drifts(full_name, drifts, config)
            return ApplyResult(repo, True)
        except gh.GhError as exc:
            return ApplyResult(repo, False, str(exc))

    out: list[ApplyResult] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(run, t) for t in targets]
        for future in as_completed(futures):
            res = future.result()
            out.append(res)
            if on_result:
                on_result(res)
    return out
