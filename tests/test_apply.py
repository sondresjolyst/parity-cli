from parity_cli import apply, gh
from parity_cli.model import FileResult, Kind, Status

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
