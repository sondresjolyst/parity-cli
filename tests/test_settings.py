from parity_cli import gh, settings

_REPO = gh.Repo("r", "o/r", "main", False, False, False)


def test_settings_drift(monkeypatch, config):
    monkeypatch.setattr(gh, "get_repo", lambda fn: {
        "delete_branch_on_merge": False,          # drift (want True)
        "squash_merge_commit_title": "COMMIT_OR_PR_TITLE",  # drift (want PR_TITLE)
        "squash_merge_commit_message": "PR_BODY",  # ok
        "has_wiki": True,                          # drift (want False)
        "allow_update_branch": True,               # ok
    })
    monkeypatch.setattr(gh, "workflow_permissions", lambda fn: {
        "default_workflow_permissions": "write",   # drift (want read)
        "can_approve_pull_request_reviews": True,  # ok
    })
    monkeypatch.setattr(gh, "vulnerability_alerts_enabled", lambda fn: True)   # ok
    monkeypatch.setattr(gh, "automated_security_fixes_enabled", lambda fn: False)  # drift

    result = settings.scan_repo_settings(_REPO, config)
    keys = {d.key for d in result.drift}
    assert keys == {
        "delete_branch_on_merge",
        "squash_merge_commit_title",
        "has_wiki",
        "actions_default_workflow_permissions",
        "dependabot_security_updates",
    }


def test_no_drift_when_matching(monkeypatch, config):
    monkeypatch.setattr(gh, "get_repo", lambda fn: {
        "delete_branch_on_merge": True,
        "squash_merge_commit_title": "PR_TITLE",
        "squash_merge_commit_message": "PR_BODY",
        "has_wiki": False,
        "allow_update_branch": True,
    })
    monkeypatch.setattr(gh, "workflow_permissions", lambda fn: {
        "default_workflow_permissions": "read",
        "can_approve_pull_request_reviews": True,
    })
    monkeypatch.setattr(gh, "vulnerability_alerts_enabled", lambda fn: True)
    monkeypatch.setattr(gh, "automated_security_fixes_enabled", lambda fn: True)

    assert settings.scan_repo_settings(_REPO, config).drift == []
