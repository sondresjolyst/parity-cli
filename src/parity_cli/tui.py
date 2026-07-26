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
from textual.widgets import (
    DataTable,
    Footer,
    Header,
    Static,
    TabbedContent,
    TabPane,
)

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
        Binding("a", "apply", "Apply"),
        Binding("q", "quit", "Quit"),
    ]

    def __init__(self, config: Config) -> None:
        super().__init__()
        self.config = config
        self.results: dict[str, RepoResult] = {}
        self.selected: set[str] = set()
        self.prs: dict[str, str] = {}
        self.settings_results: list[settings_mod.RepoSettings] = []
        self.settings_selected: set[tuple[str, str]] = set()
        self._pending_settings: dict[str, set[str]] = {}
        self._settings_loaded = False
        self._scan_gen = 0

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with TabbedContent(initial="drift"):
            with TabPane("Drift", id="drift"):
                yield DataTable(id="repos", cursor_type="row", zebra_stripes=True)
            with TabPane("Settings", id="settings"):
                yield DataTable(id="settings-table", cursor_type="row", zebra_stripes=True)
        yield Footer()

    def on_mount(self) -> None:
        repos = self.query_one("#repos", DataTable)
        repos.add_columns(
            "", "Repo", "Languages", "Dependabot", "CODEOWNERS", "Workflows", "PR"
        )
        settings_table = self.query_one("#settings-table", DataTable)
        settings_table.add_columns("", "Repo", "Setting", "Current", "Desired")
        self.title = f"parity — {self.config.owner}"
        self._scan()

    def _active(self) -> str:
        return self.query_one(TabbedContent).active

    def on_tabbed_content_tab_activated(
        self, event: TabbedContent.TabActivated
    ) -> None:
        if event.pane.id == "settings":
            if not self._settings_loaded:
                self._settings_loaded = True
                self._scan_settings()
        elif event.pane.id == "drift" and not self.results:
            self._scan()

    # ---- shared scan/apply plumbing (used by both tabs) ----

    @work(thread=True, exclusive=True, group="scan")
    def _run_scan(self, label, scan_fn, populate) -> None:
        gen = self.call_from_thread(self._scan_start, label)
        results = scan_fn(
            lambda total: self.call_from_thread(self._scan_total, gen, total),
            lambda: self.call_from_thread(self._scan_step, gen),
        )
        self.call_from_thread(populate, gen, results)

    @work(thread=True, exclusive=True)
    def _run_apply(self, run_apply, on_each, after=None) -> None:
        run_apply(lambda res: self.call_from_thread(on_each, res))
        if after is not None:
            self.call_from_thread(after)

    def _scan_start(self, label: str) -> int:
        self._scan_gen += 1
        self._scan_label = label
        self._scan_done = 0
        self._scan_total_n = 0
        self.sub_title = f"{label}…"
        return self._scan_gen

    def _scan_total(self, gen: int, total: int) -> None:
        if gen != self._scan_gen:
            return
        self._scan_total_n = total
        self.sub_title = f"{self._scan_label} 0/{total}"

    def _scan_step(self, gen: int) -> None:
        if gen != self._scan_gen:
            return
        self._scan_done += 1
        self.sub_title = f"{self._scan_label} {self._scan_done}/{self._scan_total_n}"

    # ---- drift tab ----

    def _scan(self) -> None:
        def run(on_start, on_progress):
            results = drift.scan(
                self.config, on_start=on_start, on_progress=on_progress
            )
            prs: dict[str, str] = {}
            try:
                for pr in gh.search_prs(self.config.owner, self.config.branch_name):
                    prs[pr.get("repository", {}).get("name", "")] = pr.get("url", "")
            except gh.GhError:
                pass
            return results, prs

        self._run_scan("scanning", run, self._populate)

    def _populate(self, gen: int, data) -> None:
        results, prs = data
        self.results = {r.repo: r for r in results}
        self.prs = prs
        table = self.query_one("#repos", DataTable)
        table.clear()
        for r in sorted(results, key=lambda x: x.repo.lower()):
            table.add_row(*self._row(r), key=r.repo)
        if gen == self._scan_gen:
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
        table = self.query_one("#repos", DataTable)
        if table.row_count == 0:
            return None
        return table.coordinate_to_cell_key((table.cursor_row, 0)).row_key.value

    def _refresh_row(self, repo: str) -> None:
        table = self.query_one("#repos", DataTable)
        r = self.results[repo]
        for col, value in zip(table.columns.keys(), self._row(r)):
            table.update_cell(repo, col, value)

    def action_toggle(self) -> None:
        if self._active() == "settings":
            self._toggle_setting()
            return
        repo = self._cursor_repo()
        if not repo:
            return
        self.selected.symmetric_difference_update({repo})
        self._refresh_row(repo)

    def action_diff(self) -> None:
        if self._active() != "drift":
            return
        repo = self._cursor_repo()
        if repo and repo in self.results:
            self.push_screen(DiffScreen(self.results[repo]))

    def action_open_pr(self) -> None:
        if self._active() != "drift":
            return
        repo = self._cursor_repo()
        url = self.prs.get(repo) if repo else None
        if url:
            webbrowser.open(url)
            self.notify(f"opening {repo} PR")
        else:
            self.notify("no open parity PR for this repo", severity="warning")

    def _apply(self, repos: list[str]) -> None:
        targets = [self.results[r] for r in repos]
        self._run_apply(
            lambda report: apply_mod.apply_many(
                targets, self.config, on_result=report
            ),
            self._apply_done,
        )

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

    def _apply_drift(self) -> None:
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

    # ---- settings tab ----

    def _scan_settings(self) -> None:
        self._run_scan(
            "checking settings",
            lambda on_start, on_progress: settings_mod.scan_settings(
                self.config, on_start=on_start, on_progress=on_progress
            ),
            self._populate_settings,
        )

    def _settings_mark(self, repo: str, key: str) -> Text:
        return (Text("●", style="cyan")
                if (repo, key) in self.settings_selected else Text(" "))

    def _populate_settings(
        self, gen: int, results: list[settings_mod.RepoSettings]
    ) -> None:
        self.settings_results = results
        table = self.query_one("#settings-table", DataTable)
        table.clear()
        drifted = 0
        for r in sorted(results, key=lambda x: x.repo.lower()):
            for d in r.drift:
                drifted += 1
                table.add_row(
                    self._settings_mark(r.repo, d.key), r.repo, d.key,
                    Text(str(d.current), style="red"),
                    Text(str(d.desired), style="green"),
                    key=f"{r.repo}|{d.key}",
                )
        if gen == self._scan_gen:
            self._set_settings_subtitle()

    def _set_settings_subtitle(self) -> None:
        drifted = sum(len(r.drift) for r in self.settings_results)
        self.sub_title = (
            f"settings · {drifted} drift across {len(self.settings_results)} repos"
        )

    def _settings_cursor(self) -> tuple[str, str] | None:
        table = self.query_one("#settings-table", DataTable)
        if table.row_count == 0:
            return None
        row_key = table.coordinate_to_cell_key((table.cursor_row, 0)).row_key.value
        repo, _, key = row_key.partition("|")
        return repo, key

    def _toggle_setting(self) -> None:
        pair = self._settings_cursor()
        if not pair:
            return
        self.settings_selected.symmetric_difference_update({pair})
        table = self.query_one("#settings-table", DataTable)
        table.update_cell(f"{pair[0]}|{pair[1]}",
                          next(iter(table.columns.keys())),
                          self._settings_mark(*pair))

    def _apply_settings(self, targets: list[tuple[str, str, list]]) -> None:
        self._pending_settings = {repo: {d.key for d in drifts}
                                  for _, repo, drifts in targets}
        self._run_apply(
            lambda report: settings_mod.apply_many(
                targets, self.config, on_result=report
            ),
            self._settings_applied,
        )

    def _settings_applied(self, res: settings_mod.ApplyResult) -> None:
        if not res.ok:
            self.notify(f"{res.repo}: {res.error}", severity="error", timeout=8)
            return
        keys = self._pending_settings.get(res.repo, set())
        table = self.query_one("#settings-table", DataTable)
        for key in keys:
            try:
                table.remove_row(f"{res.repo}|{key}")
            except Exception:  # noqa: BLE001
                pass
            self.settings_selected.discard((res.repo, key))
        for rs in self.settings_results:
            if rs.repo == res.repo:
                rs.drift = [d for d in rs.drift if d.key not in keys]
        self._set_settings_subtitle()
        self.notify(f"{res.repo} settings fixed")

    def _apply_settings_drift(self) -> None:
        if not self.settings_selected:
            self.notify("select settings first (space)", severity="warning")
            return
        lookup = {r.repo: r for r in self.settings_results}
        by_repo: dict[str, set[str]] = {}
        for repo, key in self.settings_selected:
            by_repo.setdefault(repo, set()).add(key)
        targets = []
        for repo, keys in by_repo.items():
            rs = lookup.get(repo)
            if not rs:
                continue
            drifts = [d for d in rs.drift if d.key in keys]
            if drifts:
                targets.append((rs.full_name, repo, drifts))
        if not targets:
            self.notify("nothing to apply", severity="warning")
            return
        self.settings_selected.clear()
        self.notify(f"applying settings to {len(targets)} repo(s)…")
        self._apply_settings(targets)

    # ---- shared actions (dispatch by active tab) ----

    def action_rescan(self) -> None:
        if self._active() == "settings":
            self._scan_settings()
        else:
            self._scan()

    def action_apply(self) -> None:
        if self._active() == "settings":
            self._apply_settings_drift()
        else:
            self._apply_drift()
