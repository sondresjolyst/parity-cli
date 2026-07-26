from parity_cli import messages
from parity_cli.model import FileResult, Kind, Status


def _fr(path, kind, status):
    return FileResult(path, kind, status, "desired", None if status is Status.MISSING else "cur")


def test_single_dependabot_add():
    subject, body = messages.build([_fr(".github/dependabot.yml", Kind.DEPENDABOT, Status.MISSING)])
    assert subject == "ci: add `dependabot.yml`"
    assert body == "- add `.github/dependabot.yml`"


def test_codeowners_update_is_chore():
    subject, _ = messages.build([_fr(".github/CODEOWNERS", Kind.CODEOWNERS, Status.DRIFT)])
    assert subject == "chore: update `CODEOWNERS`"


def test_multiple_workflows_listed():
    subject, _ = messages.build([
        _fr(".github/workflows/ci.yml", Kind.WORKFLOW, Status.MISSING),
        _fr(".github/workflows/lint.yml", Kind.WORKFLOW, Status.MISSING),
    ])
    assert subject == "ci: add `ci` and `lint` workflows"


def test_mixed_kinds_join():
    subject, body = messages.build([
        _fr(".github/dependabot.yml", Kind.DEPENDABOT, Status.MISSING),
        _fr(".github/workflows/dependency-review.yml", Kind.WORKFLOW, Status.MISSING),
    ])
    assert subject == "ci: add `dependabot.yml` and `dependency-review` workflow"
    assert body.count("\n") == 1


def test_mixed_actions_split_by_verb():
    subject, _ = messages.build([
        _fr(".github/dependabot.yml", Kind.DEPENDABOT, Status.MISSING),
        _fr(".github/CODEOWNERS", Kind.CODEOWNERS, Status.DRIFT),
    ])
    assert subject == "ci: add `dependabot.yml`; update `CODEOWNERS`"


def test_remove_extra_workflow():
    subject, body = messages.build(
        [_fr(".github/workflows/dependency-review.yml", Kind.WORKFLOW, Status.EXTRA)]
    )
    assert subject == "ci: remove `dependency-review` workflow"
    assert body == "- remove `.github/workflows/dependency-review.yml`"


def test_add_and_remove_split():
    subject, _ = messages.build([
        _fr(".github/dependabot.yml", Kind.DEPENDABOT, Status.MISSING),
        _fr(".github/workflows/dependency-review.yml", Kind.WORKFLOW, Status.EXTRA),
    ])
    assert subject == "ci: add `dependabot.yml`; remove `dependency-review` workflow"


def test_empty():
    assert messages.build([])[0] == "chore: no changes"
