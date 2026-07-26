"""Push a repo's changed files as a single commit on a branch and open a PR."""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass

from . import gh, messages
from .config import Config
from .model import RepoResult, Status


@dataclass
class ApplyResult:
    repo: str
    pushed: bool
    pr_url: str | None = None
    commit: str | None = None
    skipped_reason: str | None = None
    error: str | None = None


def apply_repo(result: RepoResult, config: Config, *, open_pr: bool = True) -> ApplyResult:
    changes = result.changed
    if not changes:
        return ApplyResult(result.repo, pushed=False, skipped_reason="already in sync")
    if result.error:
        return ApplyResult(result.repo, pushed=False, error=result.error)

    subject, body = messages.build(changes)
    branch = config.branch_name

    try:
        base_sha = gh.ref_sha(result.full_name, result.default_branch)
        if not base_sha:
            return ApplyResult(result.repo, pushed=False,
                               error=f"no ref for {result.default_branch}")
        base_tree = gh.commit_tree_sha(result.full_name, base_sha)
        writes = [(f.path, f.desired) for f in changes if f.status is not Status.EXTRA]
        deletes = [f.path for f in changes if f.status is Status.EXTRA]
        tree = gh.create_tree(result.full_name, base_tree, writes, deletes)
        commit = gh.create_commit(result.full_name, f"{subject}\n\n{body}", tree, base_sha)
        gh.upsert_branch(result.full_name, branch, commit)

        pr_url = None
        if open_pr:
            existing = gh.find_open_pr(result.full_name, branch)
            if existing:
                gh.update_pr(result.full_name, existing["number"], subject, body)
                pr_url = existing["url"]
            else:
                pr_url = gh.open_pr(
                    result.full_name, branch, result.default_branch, subject, body
                )
        return ApplyResult(result.repo, pushed=True, pr_url=pr_url, commit=commit[:7])
    except gh.GhError as exc:
        return ApplyResult(result.repo, pushed=False, error=str(exc))


def apply_many(
    results: list[RepoResult],
    config: Config,
    *,
    open_pr: bool = True,
    workers: int = 8,
    on_result: Callable[[ApplyResult], None] | None = None,
) -> list[ApplyResult]:
    out: list[ApplyResult] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [
            pool.submit(apply_repo, r, config, open_pr=open_pr) for r in results
        ]
        for future in as_completed(futures):
            res = future.result()
            out.append(res)
            if on_result:
                on_result(res)
    return out
