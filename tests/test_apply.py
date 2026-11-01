from parity_cli import apply, gh
from parity_cli.model import FileResult, Kind, RepoResult, Status

WORKFLOW = FileResult(".github/workflows/ci.yml", Kind.WORKFLOW, Status.DRIFT, "", "")
DEPENDABOT = FileResult(".github/dependabot.yml", Kind.DEPENDABOT, Status.DRIFT, "", "")


def test_explain_adds_hint_when_workflow_scope_missing(monkeypatch):
    monkeypatch.setattr(gh, "token_scopes", lambda: {"repo", "read:org"})

    msg = apply._explain("gh: Not Found (HTTP 404)", [DEPENDABOT, WORKFLOW])

    assert msg == f"gh: Not Found (HTTP 404): {apply.WORKFLOW_SCOPE_HINT}"


def test_explain_keeps_error_when_scope_present(monkeypatch):
    monkeypatch.setattr(gh, "token_scopes", lambda: {"repo", "workflow"})

    assert (
        apply._explain("gh: Not Found (HTTP 404)", [WORKFLOW])
        == "gh: Not Found (HTTP 404)"
    )


def test_explain_keeps_error_when_scopes_unknown(monkeypatch):
    monkeypatch.setattr(gh, "token_scopes", lambda: None)

    assert (
        apply._explain("gh: Not Found (HTTP 404)", [WORKFLOW])
        == "gh: Not Found (HTTP 404)"
    )


def test_explain_skips_scope_check_without_workflow_changes(monkeypatch):
    def fail():
        raise AssertionError("scopes should not be checked")

    monkeypatch.setattr(gh, "token_scopes", fail)

    assert (
        apply._explain("gh: Not Found (HTTP 404)", [DEPENDABOT])
        == "gh: Not Found (HTTP 404)"
    )
    assert apply._explain("gh: Bad credentials (HTTP 401)", [WORKFLOW]) == (
        "gh: Bad credentials (HTTP 401)"
    )


def test_only_renovate_moves_the_repo_as_one_unit(config, monkeypatch):
    trees = []
    monkeypatch.setattr(gh, "ref_sha", lambda *a, **k: "base")
    monkeypatch.setattr(gh, "commit_tree_sha", lambda *a, **k: "tree")
    monkeypatch.setattr(
        gh, "create_tree", lambda _r, _b, writes, deletes: trees.append((writes, deletes)) or "new"
    )
    monkeypatch.setattr(gh, "create_commit", lambda *a, **k: "commit1")
    monkeypatch.setattr(gh, "upsert_branch", lambda *a, **k: None)
    result = RepoResult("r", "o/r", "main", [], files=[
        FileResult("renovate.json", Kind.RENOVATE, Status.MISSING, "{}", None),
        FileResult(".github/dependabot.yml", Kind.RENOVATE, Status.EXTRA, "", "x"),
        FileResult(".github/CODEOWNERS", Kind.CODEOWNERS, Status.EXTRA, "", "x"),
    ])
    out = apply.apply_repo(result, config, open_pr=False, only={Kind.RENOVATE})
    assert out.pushed
    assert trees == [([("renovate.json", "{}")], [".github/dependabot.yml"])]
