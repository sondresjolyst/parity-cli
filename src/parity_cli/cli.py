"""parity command line interface."""

from __future__ import annotations

import difflib
from pathlib import Path

import typer
from rich.console import Console
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rich.progress import Progress
from rich.table import Table

from . import apply as apply_mod
from . import config as config_mod
from . import drift, messages
from .model import Status

app = typer.Typer(
    add_completion=False,
    help="See and fix drift in dependabot.yml, CODEOWNERS and shared workflows.",
    no_args_is_help=True,
)
console = Console()

CONFIG_OPT = typer.Option("parity.yml", "--config", "-c", help="Path to config file.")

_STATUS_STYLE = {
    Status.MATCH: "green",
    Status.DRIFT: "yellow",
    Status.MISSING: "red",
    Status.EXTRA: "magenta",
}


def _with_progress(description, run):
    with Progress(
        TextColumn("[bold]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
        transient=True,
        console=console,
    ) as progress:
        state: dict[str, int] = {}

        def start(total: int) -> None:
            state["task"] = progress.add_task(description, total=total)

        def step() -> None:
            progress.advance(state["task"])

        return run(start, step)


def _scan(cfg):
    return _with_progress(
        f"scanning {cfg.owner}",
        lambda start, step: drift.scan(cfg, on_start=start, on_progress=step),
    )


@app.command()
def status(config: Path = CONFIG_OPT) -> None:
    """Show a drift table across all repos."""
    cfg = config_mod.load(config)
    results = _scan(cfg)

    table = Table(show_lines=False)
    table.add_column("Repo", no_wrap=True)
    table.add_column("Languages")
    table.add_column("Dependabot")
    table.add_column("CODEOWNERS")
    table.add_column("Workflows")

    for r in sorted(results, key=lambda x: x.repo.lower()):
        if r.error:
            table.add_row(r.repo, "[red]error[/]", r.error, "", "")
            continue
        cells = {"dependabot": [], "codeowners": [], "workflow": []}
        for f in r.files:
            cells[f.kind.value].append(f.status)
        table.add_row(
            r.repo,
            ", ".join(r.languages) or "-",
            _cell(cells["dependabot"]),
            _cell(cells["codeowners"]),
            _cell(cells["workflow"]),
        )
    console.print(table)
    _summary(results)


def _worst(statuses: list[Status]) -> Status:
    for status in (Status.MISSING, Status.DRIFT, Status.EXTRA):
        if status in statuses:
            return status
    return Status.MATCH


def _cell(statuses: list[Status]) -> str:
    if not statuses:
        return "[dim]-[/]"
    worst = _worst(statuses)
    label = "ok" if worst is Status.MATCH else worst.value
    return f"[{_STATUS_STYLE[worst]}]{label}[/]"


def _summary(results) -> None:
    drifted = [r for r in results if r.changed and not r.error]
    console.print(
        f"\n{len(results)} repos, [yellow]{len(drifted)}[/] with drift. "
        "Run [bold]parity diff <repo>[/] or [bold]parity apply[/]."
    )


@app.command()
def diff(
    repo: str = typer.Argument(..., help="Repo short name."),
    config: Path = CONFIG_OPT,
) -> None:
    """Show unified diffs for a single repo."""
    cfg = config_mod.load(config)
    from . import gh

    match = next(
        (r for r in gh.list_repos(cfg.owner, include_archived=cfg.include_archived,
                                  include_forks=cfg.include_forks)
         if r.name == repo),
        None,
    )
    if match is None:
        console.print(f"[red]repo not found:[/] {repo}")
        raise typer.Exit(1)

    result = drift.scan_repo(match, cfg)
    if result.error:
        console.print(f"[red]{result.error}[/]")
        raise typer.Exit(1)
    if not result.changed:
        console.print("[green]in sync[/]")
        return

    for f in result.changed:
        console.rule(f"{f.path} [{_STATUS_STYLE[f.status]}]{f.status.value}[/]")
        current = (f.current or "").splitlines(keepends=True)
        desired = f.desired.splitlines(keepends=True)
        for line in difflib.unified_diff(current, desired, "current", "desired"):
            style = ("green" if line.startswith("+")
                     else "red" if line.startswith("-") else "dim")
            console.print(f"[{style}]{line.rstrip()}[/]")


@app.command()
def apply(
    repo: list[str] = typer.Option(None, "--repo", "-r", help="Limit to repo(s)."),
    no_pr: bool = typer.Option(False, "--no-pr", help="Push branch, skip PR."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation."),
    config: Path = CONFIG_OPT,
) -> None:
    """Create a branch, commit, and open a PR per repo with drift."""
    cfg = config_mod.load(config)
    results = [r for r in _scan(cfg) if r.changed and not r.error]
    if repo:
        results = [r for r in results if r.repo in repo]
    if not results:
        console.print("[green]nothing to do — all in sync[/]")
        return

    for r in results:
        subject, _ = messages.build(r.changed)
        console.print(f"  [yellow]{r.repo}[/]: {subject}")
    if not yes and not typer.confirm(f"\nApply to {len(results)} repo(s)?"):
        raise typer.Abort()

    with Progress(
        TextColumn("[bold]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
        transient=True,
        console=console,
    ) as progress:
        task = progress.add_task("applying", total=len(results))

        def report(res: apply_mod.ApplyResult) -> None:
            progress.advance(task)
            if res.error:
                progress.console.print(f"[red]✗ {res.repo}[/]: {res.error}")
            elif res.pushed:
                where = res.pr_url or f"branch {cfg.branch_name}"
                progress.console.print(f"[green]✓ {res.repo}[/] {res.commit} → {where}")

        apply_mod.apply_many(results, cfg, open_pr=not no_pr, on_result=report)


@app.command()
def prs(config: Path = CONFIG_OPT) -> None:
    """List open PRs parity has created across repos."""
    from . import gh

    cfg = config_mod.load(config)
    rows = gh.search_prs(cfg.owner, cfg.branch_name)
    if not rows:
        console.print(f"[green]no open parity PRs[/] (branch {cfg.branch_name})")
        return

    for r in rows:
        name = r.get("repository", {}).get("name", "?")
        date = (r.get("createdAt") or "")[:10]
        console.print(f"[bold]{name}[/]  [dim]{date}[/]")
        console.print(f"  [cyan]{r.get('url', '')}[/]", highlight=False)
    console.print(f"\n{len(rows)} open parity PR(s).")


@app.command()
def settings(
    repo: list[str] = typer.Option(None, "--repo", "-r", help="Limit to repo(s)."),
    apply: bool = typer.Option(False, "--apply", help="Apply the fixes."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation."),
    config: Path = CONFIG_OPT,
) -> None:
    """Show (and optionally fix) repo settings drift across all repos."""
    from . import settings as settings_mod

    cfg = config_mod.load(config)
    if not cfg.settings:
        console.print("[yellow]no settings configured in parity.yml[/]")
        return
    results = _with_progress(
        f"checking settings {cfg.owner}",
        lambda start, step: settings_mod.scan_settings(
            cfg, on_start=start, on_progress=step
        ),
    )
    drifted = [r for r in results if r.drift and not r.error]
    if repo:
        drifted = [r for r in drifted if r.repo in repo]

    table = Table(show_lines=False)
    table.add_column("Repo", no_wrap=True)
    table.add_column("Setting", no_wrap=True)
    table.add_column("Current")
    table.add_column("Desired")
    for r in sorted(drifted, key=lambda x: x.repo.lower()):
        for d in r.drift:
            table.add_row(r.repo, d.key, f"[red]{d.current}[/]", f"[green]{d.desired}[/]")
    console.print(table)
    console.print(f"\n{len(drifted)} repo(s) with settings drift.")

    if not apply or not drifted:
        return
    if not yes and not typer.confirm(f"Apply fixes to {len(drifted)} repo(s)?"):
        raise typer.Abort()
    counts = {r.repo: len(r.drift) for r in drifted}
    targets = [(r.full_name, r.repo, r.drift) for r in drifted]

    def report(res: settings_mod.ApplyResult) -> None:
        if res.ok:
            console.print(f"[green]✓ {res.repo}[/] ({counts[res.repo]} fixed)")
        else:
            console.print(f"[red]✗ {res.repo}[/]: {res.error}")

    settings_mod.apply_many(targets, cfg, on_result=report)


@app.command()
def tui(config: Path = CONFIG_OPT) -> None:
    """Launch the interactive drift dashboard."""
    from .tui import ParityApp

    cfg = config_mod.load(config)
    ParityApp(cfg).run()


if __name__ == "__main__":
    app()
