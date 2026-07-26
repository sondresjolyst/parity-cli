"""Shared data types."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Kind(str, Enum):
    DEPENDABOT = "dependabot"
    CODEOWNERS = "codeowners"
    WORKFLOW = "workflow"
    FILE = "file"


class Status(str, Enum):
    MATCH = "match"      # repo file equals desired
    DRIFT = "drift"      # repo file exists but differs
    MISSING = "missing"  # desired file absent in repo
    EXTRA = "extra"      # managed file present but excluded for this repo


@dataclass(frozen=True)
class DesiredFile:
    path: str          # repo-relative, e.g. ".github/dependabot.yml"
    kind: Kind
    content: str


@dataclass
class FileResult:
    path: str
    kind: Kind
    status: Status
    desired: str
    current: str | None  # None when missing


@dataclass
class RepoResult:
    repo: str            # short name
    full_name: str
    default_branch: str
    languages: list[str]
    private: bool = False
    files: list[FileResult] = field(default_factory=list)
    error: str | None = None

    @property
    def changed(self) -> list[FileResult]:
        return [f for f in self.files if f.status is not Status.MATCH]

    @property
    def worst(self) -> Status:
        statuses = {f.status for f in self.files}
        for status in (Status.MISSING, Status.DRIFT, Status.EXTRA):
            if status in statuses:
                return status
        return Status.MATCH
