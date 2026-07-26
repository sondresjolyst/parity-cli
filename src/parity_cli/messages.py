"""Generate Conventional Commit messages and PR text from a change set."""

from __future__ import annotations

from .model import FileResult, Kind, Status


def _workflow_name(path: str) -> str:
    return path.rsplit("/", 1)[-1].removesuffix(".yml").removesuffix(".yaml")


def _noun(kind: Kind, files: list[FileResult]) -> str:
    if kind is Kind.DEPENDABOT:
        return "`dependabot.yml`"
    if kind is Kind.CODEOWNERS:
        return "`CODEOWNERS`"
    if kind is Kind.FILE:
        return _join([f"`{f.path.rsplit('/', 1)[-1]}`" for f in sorted(files, key=lambda x: x.path)])
    names = sorted(_workflow_name(f.path) for f in files)
    suffix = "workflow" if len(names) == 1 else "workflows"
    return f"{_join([f'`{n}`' for n in names])} {suffix}"


def _join(items: list[str]) -> str:
    if len(items) <= 1:
        return items[0] if items else ""
    return ", ".join(items[:-1]) + f" and {items[-1]}"


def _commit_type(kinds: set[Kind]) -> str:
    if kinds == {Kind.CODEOWNERS}:
        return "chore"
    return "ci"


_ORDER = (Kind.DEPENDABOT, Kind.CODEOWNERS, Kind.WORKFLOW, Kind.FILE)


def _clause(verb: str, changes: list[FileResult]) -> str:
    by_kind: dict[Kind, list[FileResult]] = {}
    for f in changes:
        by_kind.setdefault(f.kind, []).append(f)
    nouns = [_noun(k, by_kind[k]) for k in _ORDER if k in by_kind]
    return f"{verb} {_join(nouns)}"


def build(changes: list[FileResult]) -> tuple[str, str]:
    if not changes:
        return ("chore: no changes", "")

    ctype = _commit_type({f.kind for f in changes})
    buckets = [
        ("add", [f for f in changes if f.status is Status.MISSING]),
        ("update", [f for f in changes if f.status is Status.DRIFT]),
        ("remove", [f for f in changes if f.status is Status.EXTRA]),
    ]
    clauses = [_clause(verb, group) for verb, group in buckets if group]
    subject = f"{ctype}: " + "; ".join(clauses)

    body = "\n".join(f"- {_action(f.status)} `{f.path}`" for f in changes)
    return subject, body


def _action(status: Status) -> str:
    if status is Status.MISSING:
        return "add"
    if status is Status.EXTRA:
        return "remove"
    return "update"
