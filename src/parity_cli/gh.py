"""Thin wrapper over the authenticated `gh` CLI."""

from __future__ import annotations

import base64
import json
import shutil
import subprocess
from dataclasses import dataclass


class GhError(RuntimeError):
    """A `gh` invocation failed."""


def _run(args: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    if shutil.which("gh") is None:
        raise GhError("`gh` CLI not found on PATH. Install it and run `gh auth login`.")
    proc = subprocess.run(
        ["gh", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if check and proc.returncode != 0:
        raise GhError(proc.stderr.strip() or f"gh {' '.join(args)} failed")
    return proc


def api(path: str, *, method: str = "GET", fields: dict[str, str] | None = None,
        paginate: bool = False) -> object:
    """Call the GitHub REST API via `gh api` and return parsed JSON."""
    args = ["api", "-H", "Accept: application/vnd.github+json", "-X", method]
    if paginate:
        args.append("--paginate")
    for key, value in (fields or {}).items():
        args += ["-f", f"{key}={value}"]
    args.append(path)
    out = _run(args).stdout.strip()
    if not out:
        return None
    if paginate:
        return _merge_paginated(out)
    return json.loads(out)


def _merge_paginated(out: str) -> list:
    decoder = json.JSONDecoder()
    idx = 0
    merged: list = []
    length = len(out)
    while idx < length:
        while idx < length and out[idx] in " \t\r\n":
            idx += 1
        if idx >= length:
            break
        value, end = decoder.raw_decode(out, idx)
        if isinstance(value, list):
            merged.extend(value)
        else:
            merged.append(value)
        idx = end
    return merged


def current_login() -> str:
    return str(api("user")["login"])  # type: ignore[index]


@dataclass(frozen=True)
class Repo:
    name: str
    full_name: str
    default_branch: str
    archived: bool
    fork: bool
    private: bool


def list_user_teams() -> list[tuple[str, str]]:
    """List (org_login, team_slug) pairs for the authenticated user."""
    raw = api("/user/teams", paginate=True) or []
    teams: list[tuple[str, str]] = []
    for item in raw:
        org = item.get("organization") or {}
        login = org.get("login")
        slug = item.get("slug")
        if not login or not slug:
            continue
        teams.append((str(login), str(slug)))
    return sorted(teams)


def list_repos(owner: str, *, include_archived: bool = False,
               include_forks: bool = False) -> list[Repo]:
    """List repos for a user or org."""
    fields = "name,nameWithOwner,defaultBranchRef,isArchived,isFork,isPrivate"
    out = _run(["repo", "list", owner, "--limit", "1000", "--json", fields]).stdout
    raw = json.loads(out) if out.strip() else []
    repos: list[Repo] = []
    for item in raw:
        if item.get("isArchived") and not include_archived:
            continue
        if item.get("isFork") and not include_forks:
            continue
        branch_ref = item.get("defaultBranchRef") or {}
        repos.append(
            Repo(
                name=item["name"],
                full_name=item["nameWithOwner"],
                default_branch=branch_ref.get("name") or "main",
                archived=bool(item.get("isArchived")),
                fork=bool(item.get("isFork")),
                private=bool(item.get("isPrivate")),
            )
        )
    return sorted(repos, key=lambda r: r.name.lower())


# GitHub permission hierarchy, lowest to highest. A repo satisfies a given
# minimum permission if any equal-or-higher level in this list is truthy.
PERMISSION_LEVELS = ["pull", "triage", "push", "maintain", "admin"]


def _meets_min_permission(permissions: dict[str, object], minimum: str) -> bool:
    if minimum not in PERMISSION_LEVELS:
        raise ValueError(
            f"Unsupported team permission {minimum!r}; expected one of "
            f"{PERMISSION_LEVELS}"
        )
    threshold = PERMISSION_LEVELS.index(minimum)
    return any(
        permissions.get(level) for level in PERMISSION_LEVELS[threshold:]
    )


def list_team_repos(
    org: str,
    team_slug: str,
    *,
    min_permission: str = "push",
    include_archived: bool = False,
    include_forks: bool = False,
) -> list[Repo]:
    """List repos the team has at least `min_permission` on.

    "push" (default) is enough to apply file drift; "admin" is required
    for `parity settings --apply`.
    """
    raw = api(f"/orgs/{org}/teams/{team_slug}/repos", paginate=True) or []
    repos: list[Repo] = []
    for item in raw:
        if not _meets_min_permission(item.get("permissions") or {}, min_permission):
            continue
        if item.get("archived") and not include_archived:
            continue
        if item.get("fork") and not include_forks:
            continue
        repos.append(
            Repo(
                name=item["name"],
                full_name=item["full_name"],
                default_branch=item.get("default_branch") or "main",
                archived=bool(item.get("archived")),
                fork=bool(item.get("fork")),
                private=bool(item.get("private")),
            )
        )
    return sorted(repos, key=lambda r: r.name.lower())


def list_repos_for_teams(
    teams: list[str],
    *,
    min_permission: str = "push",
    include_archived: bool = False,
    include_forks: bool = False,
) -> list[Repo]:
    repos_by_full_name: dict[str, Repo] = {}
    for team in teams:
        org, sep, team_slug = team.partition("/")
        if not sep or not org or not team_slug:
            raise ValueError(
                f"Invalid team {team!r}; expected 'org/team_slug' in parity.yml"
            )
        for repo in list_team_repos(
            org,
            team_slug,
            min_permission=min_permission,
            include_archived=include_archived,
            include_forks=include_forks,
        ):
            repos_by_full_name[repo.full_name] = repo
    return sorted(repos_by_full_name.values(), key=lambda r: r.name.lower())


def languages(full_name: str) -> dict[str, int]:
    """Return {language: bytes} for a repo."""
    result = api(f"repos/{full_name}/languages")
    return dict(result or {})


def get_file(full_name: str, path: str, ref: str | None = None) -> str | None:
    """Return the decoded text of a file, or None if it does not exist."""
    url = f"repos/{full_name}/contents/{path}"
    if ref:
        url += f"?ref={ref}"
    proc = _run(["api", url], check=False)
    if proc.returncode != 0:
        if "Not Found" in proc.stderr or "404" in proc.stderr:
            return None
        raise GhError(proc.stderr.strip())
    data = json.loads(proc.stdout)
    if data.get("encoding") != "base64":
        return None
    return base64.b64decode(data["content"]).decode("utf-8")


def has_workflow_files(full_name: str, ref: str | None = None) -> bool:
    """True if the repo has at least one file under .github/workflows."""
    url = f"repos/{full_name}/contents/.github/workflows"
    if ref:
        url += f"?ref={ref}"
    proc = _run(["api", url], check=False)
    if proc.returncode != 0:
        if "Not Found" in proc.stderr or "404" in proc.stderr:
            return False
        raise GhError(proc.stderr.strip())
    data = json.loads(proc.stdout)
    return isinstance(data, list) and any(item.get("type") == "file" for item in data)


def _api_json(path: str, method: str, body: dict) -> dict:
    proc = subprocess.run(
        ["gh", "api", "-H", "Accept: application/vnd.github+json",
         "-X", method, "--input", "-", path],
        input=json.dumps(body),
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if proc.returncode != 0:
        raise GhError(proc.stderr.strip() or f"gh api {path} failed")
    return json.loads(proc.stdout) if proc.stdout.strip() else {}


def ref_sha(full_name: str, branch: str) -> str | None:
    proc = _run(["api", f"repos/{full_name}/git/ref/heads/{branch}"], check=False)
    if proc.returncode != 0:
        return None
    return json.loads(proc.stdout)["object"]["sha"]


def commit_tree_sha(full_name: str, commit_sha: str) -> str:
    data = api(f"repos/{full_name}/git/commits/{commit_sha}")
    return str(data["tree"]["sha"])  # type: ignore[index]


def create_tree(full_name: str, base_tree: str,
                files: list[tuple[str, str]],
                deletes: list[str] | None = None) -> str:
    tree: list[dict] = [
        {"path": path, "mode": "100644", "type": "blob", "content": content}
        for path, content in files
    ]
    tree += [
        {"path": path, "mode": "100644", "type": "blob", "sha": None}
        for path in (deletes or [])
    ]
    data = _api_json(
        f"repos/{full_name}/git/trees",
        "POST",
        {"base_tree": base_tree, "tree": tree},
    )
    return str(data["sha"])


def create_commit(full_name: str, message: str, tree: str, parent: str) -> str:
    data = _api_json(
        f"repos/{full_name}/git/commits",
        "POST",
        {"message": message, "tree": tree, "parents": [parent]},
    )
    return str(data["sha"])


def upsert_branch(full_name: str, branch: str, commit_sha: str) -> None:
    ref = f"heads/{branch}"
    if ref_sha(full_name, branch) is None:
        _api_json(
            f"repos/{full_name}/git/refs",
            "POST",
            {"ref": f"refs/{ref}", "sha": commit_sha},
        )
    else:
        _api_json(
            f"repos/{full_name}/git/refs/{ref}",
            "PATCH",
            {"sha": commit_sha, "force": True},
        )


def open_pr(
    full_name: str, head: str, base: str, title: str, body: str, *, draft: bool = False
) -> str:
    data = _api_json(
        f"repos/{full_name}/pulls",
        "POST",
        {"title": title, "head": head, "base": base, "body": body, "draft": draft},
    )
    return str(data["html_url"])


def get_repo(full_name: str) -> dict:
    return dict(api(f"repos/{full_name}"))  # type: ignore[arg-type]


def patch_repo(full_name: str, fields: dict) -> None:
    _api_json(f"repos/{full_name}", "PATCH", fields)


def workflow_permissions(full_name: str) -> dict:
    return dict(api(f"repos/{full_name}/actions/permissions/workflow"))  # type: ignore[arg-type]


def set_workflow_permissions(full_name: str, default_permissions: str,
                             can_approve: bool) -> None:
    _api_json(
        f"repos/{full_name}/actions/permissions/workflow",
        "PUT",
        {
            "default_workflow_permissions": default_permissions,
            "can_approve_pull_request_reviews": can_approve,
        },
    )


def vulnerability_alerts_enabled(full_name: str) -> bool:
    return _run(["api", f"repos/{full_name}/vulnerability-alerts"],
                check=False).returncode == 0


def set_vulnerability_alerts(full_name: str, enabled: bool) -> None:
    method = "PUT" if enabled else "DELETE"
    _run(["api", "-X", method, f"repos/{full_name}/vulnerability-alerts"])


def automated_security_fixes_enabled(full_name: str) -> bool:
    proc = _run(["api", f"repos/{full_name}/automated-security-fixes"], check=False)
    if proc.returncode != 0 or not proc.stdout.strip():
        return False
    return bool(json.loads(proc.stdout).get("enabled"))


def set_automated_security_fixes(full_name: str, enabled: bool) -> None:
    method = "PUT" if enabled else "DELETE"
    _run(["api", "-X", method, f"repos/{full_name}/automated-security-fixes"])


def search_prs(owner: str, head: str) -> list[dict]:
    fields = "number,title,url,repository,createdAt"
    out = _run([
        "search", "prs", f"head:{head}", "--owner", owner,
        "--state", "open", "--limit", "200", "--json", fields,
    ]).stdout
    items = json.loads(out) if out.strip() else []
    return sorted(items, key=lambda i: i.get("repository", {}).get("name", ""))


def find_open_pr(full_name: str, head: str) -> dict | None:
    login = current_login()
    proc = _run(
        ["api", f"repos/{full_name}/pulls?state=open&head={login}:{head}"],
        check=False,
    )
    if proc.returncode != 0:
        return None
    items = json.loads(proc.stdout)
    if not items:
        return None
    return {"number": items[0]["number"], "url": items[0]["html_url"]}


def update_pr(full_name: str, number: int, title: str, body: str) -> None:
    _api_json(
        f"repos/{full_name}/pulls/{number}",
        "PATCH",
        {"title": title, "body": body},
    )
