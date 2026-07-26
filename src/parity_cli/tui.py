"""Interactive drift dashboard."""

from __future__ import annotations

import difflib
import webbrowser

from rich.text import Text
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import DataTable, Footer, Header, Static

from . import apply as apply_mod
from . import drift, gh, messages
from . import settings as settings_mod
from .config import Config
from .model import RepoResult, Status

_STYLE = {
    Status.MATCH: "green",
    Status.DRIFT: "yellow",
    Status.MISSING: "red",
    Status.EXTRA: "magenta",
}


def _cell(statuses: list[Status]) -> Text:
    if not statuses:
        return Text("-", style="dim")
    worst = Status.MATCH
    for status in (Status.MISSING, Status.DRIFT, Status.EXTRA):
        if status in statuses:
            worst = status
            break
    label = "ok" if worst is Status.MATCH else worst.value
    return Text(label, style=_STYLE[worst])


class SettingsScreen(ModalScreen):
    BINDINGS = [
        Binding("escape,q", "dismiss", "Close"),
        Binding("r", "rescan", "Rescan"),
        Binding("a", "apply", "Apply all"),
    ]
    CSS = """
    SettingsScreen { align: center middle; }
    SettingsScreen VerticalScroll {
        width: 90%; height: 90%; border: round white; padding: 1 2;
    }
    """

    def __init__(self, config: Config) -> None:
        super().__init__()
        self.config = config
        self.results: list[settings_mod.RepoSettings] = []

    def compose(self) -> ComposeResult:
        with VerticalScroll():
            yield DataTable(cursor_type="row")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        table.add_columns("Repo", "Setting", "Current", "Desired")
        self.action_rescan()

    @work(thread=True, exclusive=True)
    def _scan(self) -> None:
        results = settings_mod.scan_settings(self.config)
        self.app.call_from_thread(self._populate, results)

    def _populate(self, results: list[settings_mod.RepoSettings]) -> None:
        self.results = results
        table = self.query_one(DataTable)
        table.clear()
        drifted = 0
        for r in sorted(results, key=lambda x: x.repo.lower()):
            for d in r.drift:
                drifted += 1
                table.add_row(
                    r.repo, d.key,
                    Text(str(d.current), style="red"),
                    Text(str(d.desired), style="green"),
                )
        self.title = "settings"
        self.sub_title = f"{drifted} drift across {len(results)} repos"

    def action_rescan(self) -> None:
        self.sub_title = "scanning…"
        self._scan()

    @work(thread=True, exclusive=True)
    def _apply(self, results: list[settings_mod.RepoSettings]) -> None:
        for r in results:
            try:
                settings_mod.apply_settings(r, self.config)
                self.app.call_from_thread(self.notify, f"{r.repo} fixed")
            except gh.GhError as exc:
                self.app.call_from_thread(
                    self.notify, f"{r.repo}: {exc}", severity="error"
                )
        self.app.call_from_thread(self.action_rescan)

    def action_apply(self) -> None:
        drifted = [r for r in self.results if r.drift and not r.error]
        if not drifted:
            self.notify("no settings drift", severity="warning")
            return
        self.notify(f"applying settings to {len(drifted)} repo(s)…")
        self._apply(drifted)


class DiffScreen(ModalScreen):
    BINDINGS = [Binding("escape,q", "dismiss", "Close")]

    def __init__(self, result: RepoResult) -> None:
        super().__init__()
        self.result = result

    def compose(self) -> ComposeResult:
        with VerticalScroll():
            if not self.result.changed:
                yield Static(Text("in sync", style="green"))
                return
            for f in self.result.changed:
                head = Text(f"\n{f.path}  ", style="bold")
                head.append(f.status.value, style=_STYLE[f.status])
                yield Static(head)
                current = (f.current or "").splitlines(keepends=True)
                desired = f.desired.splitlines(keepends=True)
                body = Text()
                for line in difflib.unified_diff(current, desired, "current", "desired"):
                    style = ("green" if line.startswith("+")
                             else "red" if line.startswith("-") else "dim")
                    body.append(line if line.endswith("\n") else line + "\n", style=style)
                yield Static(body)


class ParityApp(App):
    CSS = """
    DataTable { height: 1fr; }
    DiffScreen { align: center middle; }
    DiffScreen VerticalScroll { width: 90%; height: 90%; border: round white; padding: 1 2; }
    """
    BINDINGS = [
        Binding("r", "rescan", "Rescan"),
        Binding("space", "toggle", "Select"),
        Binding("d,enter", "diff", "Diff"),
        Binding("o", "open_pr", "Open PR"),
        Binding("s", "settings", "Settings"),
        Binding("a", "apply", "Apply selected"),
        Binding("q", "quit", "Quit"),
    ]

    def __init__(self, config: Config) -> None:
        super().__init__()
        self.config = config
        self.results: dict[str, RepoResult] = {}
        self.selected: set[str] = set()
        self.prs: dict[str, str] = {}

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        yield DataTable(cursor_type="row", zebra_stripes=True)
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        table.add_columns(
            "", "Repo", "Languages", "Dependabot", "CODEOWNERS", "Workflows", "PR"
        )
        self.title = f"parity — {self.config.owner}"
        self.action_rescan()

    @work(thread=True, exclusive=True)
    def _scan(self) -> None:
        self.call_from_thread(self._scan_start)

        def start(total: int) -> None:
            self.call_from_thread(self._scan_total, total)

        def step() -> None:
            self.call_from_thread(self._scan_step)

        results = drift.scan(self.config, on_start=start, on_progress=step)
        prs: dict[str, str] = {}
        try:
            for pr in gh.search_prs(self.config.owner, self.config.branch_name):
                prs[pr.get("repository", {}).get("name", "")] = pr.get("url", "")
        except gh.GhError:
            pass
        self.call_from_thread(self._populate, results, prs)

    def _scan_start(self) -> None:
        self._scan_done = 0
        self._scan_total_n = 0
        self.sub_title = "scanning…"

    def _scan_total(self, total: int) -> None:
        self._scan_total_n = total
        self.sub_title = f"scanning 0/{total}"

    def _scan_step(self) -> None:
        self._scan_done += 1
        self.sub_title = f"scanning {self._scan_done}/{self._scan_total_n}"

    def _populate(self, results: list[RepoResult], prs: dict[str, str]) -> None:
        self.results = {r.repo: r for r in results}
        self.prs = prs
        table = self.query_one(DataTable)
        table.clear()
        for r in sorted(results, key=lambda x: x.repo.lower()):
            table.add_row(*self._row(r), key=r.repo)
        self._set_subtitle()

    def _set_subtitle(self) -> None:
        drifted = sum(1 for r in self.results.values() if r.changed and not r.error)
        self.sub_title = (
            f"{len(self.results)} repos · {drifted} with drift · "
            f"{len(self.prs)} open PRs"
        )

    def _pr_cell(self, repo: str) -> Text:
        url = self.prs.get(repo)
        if not url:
            return Text(" ")
        return Text(f"#{url.rsplit('/', 1)[-1]}", style=f"link {url}")

    def _row(self, r: RepoResult) -> list:
        mark = Text("●", style="cyan") if r.repo in self.selected else Text(" ")
        if r.error:
            return [mark, r.repo, Text("error", style="red"), Text(r.error[:20]),
                    Text(""), Text(""), self._pr_cell(r.repo)]
        by_kind: dict[str, list[Status]] = {}
        for f in r.files:
            by_kind.setdefault(f.kind.value, []).append(f.status)
        workflows = by_kind.get("workflow", []) + by_kind.get("file", [])
        return [
            mark, r.repo, ", ".join(r.languages) or "-",
            _cell(by_kind.get("dependabot", [])),
            _cell(by_kind.get("codeowners", [])),
            _cell(workflows),
            self._pr_cell(r.repo),
        ]

    def _cursor_repo(self) -> str | None:
        table = self.query_one(DataTable)
        if table.row_count == 0:
            return None
        return table.coordinate_to_cell_key((table.cursor_row, 0)).row_key.value

    def _refresh_row(self, repo: str) -> None:
        table = self.query_one(DataTable)
        r = self.results[repo]
        for col, value in zip(table.columns.keys(), self._row(r)):
            table.update_cell(repo, col, value)

    def action_rescan(self) -> None:
        self.sub_title = "scanning…"
        self._scan()

    def action_toggle(self) -> None:
        repo = self._cursor_repo()
        if not repo:
            return
        self.selected.symmetric_difference_update({repo})
        self._refresh_row(repo)

    def action_diff(self) -> None:
        repo = self._cursor_repo()
        if repo and repo in self.results:
            self.push_screen(DiffScreen(self.results[repo]))

    def action_settings(self) -> None:
        self.push_screen(SettingsScreen(self.config))

    def action_open_pr(self) -> None:
        repo = self._cursor_repo()
        url = self.prs.get(repo) if repo else None
        if url:
            webbrowser.open(url)
            self.notify(f"opening {repo} PR")
        else:
            self.notify("no open parity PR for this repo", severity="warning")

    @work(thread=True, exclusive=True)
    def _apply(self, repos: list[str]) -> None:
        targets = [self.results[r] for r in repos]

        def report(res: apply_mod.ApplyResult) -> None:
            self.call_from_thread(self._apply_done, res)

        apply_mod.apply_many(targets, self.config, on_result=report)

    def _apply_done(self, res: apply_mod.ApplyResult) -> None:
        if res.error:
            self.notify(f"{res.repo}: {res.error}", severity="error", timeout=8)
            return
        if res.pr_url:
            self.prs[res.repo] = res.pr_url
        self.selected.discard(res.repo)
        if res.repo in self.results:
            self._refresh_row(res.repo)
        self._set_subtitle()
        self.notify(f"{res.repo} → {res.pr_url or res.commit}")

    def action_apply(self) -> None:
        if not self.selected:
            self.notify("select repos first (space)", severity="warning")
            return
        targets = sorted(
            r for r in self.selected
            if (res := self.results.get(r)) and res.changed and not res.error
        )
        if not targets:
            self.notify("selected repos have no changes", severity="warning")
            return
        subjects = "\n".join(
            f"{t}: {messages.build(self.results[t].changed)[0]}" for t in targets
        )
        self.notify(f"applying {len(targets)} repo(s)…\n{subjects}", timeout=4)
        self._apply(targets)
