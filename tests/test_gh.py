import pytest

from parity_cli import gh


def test_list_user_teams_parses_memberships(monkeypatch):
    monkeypatch.setattr(
        gh,
        "api",
        lambda path, paginate=False, **kwargs: [
            {"organization": {"login": "z-org"}, "slug": "platform"},
            {"organization": {"login": "a-org"}, "slug": "ops"},
        ]
        if path == "/user/teams" and paginate
        else [],
    )

    assert gh.list_user_teams() == [("a-org", "ops"), ("z-org", "platform")]


def test_list_team_repos_filters_repo_flags(monkeypatch):
    monkeypatch.setattr(
        gh,
        "api",
        lambda path, paginate=False, **kwargs: [
            {
                "name": "visible",
                "full_name": "my-org/visible",
                "default_branch": "develop",
                "archived": False,
                "fork": False,
                "private": True,
                "permissions": {"admin": True, "maintain": True, "push": True,
                                "triage": True, "pull": True},
            },
            {
                "name": "archived",
                "full_name": "my-org/archived",
                "default_branch": "main",
                "archived": True,
                "fork": False,
                "private": False,
                "permissions": {"admin": True, "maintain": True, "push": True,
                                "triage": True, "pull": True},
            },
            {
                "name": "forked",
                "full_name": "my-org/forked",
                "default_branch": "main",
                "archived": False,
                "fork": True,
                "private": False,
                "permissions": {"admin": True, "maintain": True, "push": True,
                                "triage": True, "pull": True},
            },
            {
                "name": "pull-only",
                "full_name": "my-org/pull-only",
                "default_branch": "main",
                "archived": False,
                "fork": False,
                "private": False,
                "permissions": {"admin": False, "maintain": False, "push": False,
                                "triage": True, "pull": True},
            },
            {
                "name": "mainless",
                "full_name": "my-org/mainless",
                "default_branch": None,
                "archived": False,
                "fork": False,
                "private": False,
                "permissions": {"admin": False, "maintain": True, "push": True,
                                "triage": True, "pull": True},
            },
        ]
        if path == "/orgs/my-org/teams/platform/repos" and paginate
        else [],
    )

    repos = gh.list_team_repos("my-org", "platform")

    assert repos == [
        gh.Repo("mainless", "my-org/mainless", "main", False, False, False),
        gh.Repo("visible", "my-org/visible", "develop", False, False, True),
    ]


def test_parse_scopes_reads_oauth_header():
    response = (
        "HTTP/2.0 200 OK\r\n"
        "Content-Type: application/json\r\n"
        "X-Oauth-Scopes: gist, read:org, repo\r\n"
        "\r\n"
        '{"login": "me"}'
    )

    assert gh._parse_scopes(response) == {"gist", "read:org", "repo"}


def test_parse_scopes_none_without_header():
    response = 'HTTP/2.0 200 OK\r\nContent-Type: application/json\r\n\r\n{"x-oauth-scopes": 1}'

    assert gh._parse_scopes(response) is None


def test_list_repos_for_teams_dedups_and_sorts(monkeypatch):
    team_repos = {
        "my-org/platform": [
            gh.Repo("bravo", "my-org/bravo", "main", False, False, False),
            gh.Repo("alpha", "my-org/alpha", "main", False, False, False),
        ],
        "my-org/ops": [
            gh.Repo("charlie", "my-org/charlie", "main", False, False, False),
            gh.Repo("alpha", "my-org/alpha", "main", False, False, False),
        ],
    }

    monkeypatch.setattr(
        gh,
        "list_team_repos",
        lambda org, team_slug, **kwargs: team_repos[f"{org}/{team_slug}"],
    )

    repos = gh.list_repos_for_teams(["my-org/platform", "my-org/ops"])

    assert repos == [
        gh.Repo("alpha", "my-org/alpha", "main", False, False, False),
        gh.Repo("bravo", "my-org/bravo", "main", False, False, False),
        gh.Repo("charlie", "my-org/charlie", "main", False, False, False),
    ]


class _Proc:
    def __init__(self, stdout="", stderr="", returncode=0):
        self.stdout, self.stderr, self.returncode = stdout, stderr, returncode


def test_repo_paths_lists_files_only(monkeypatch):
    body = '{"truncated": false, "tree": [{"path": "a", "type": "tree"}, {"path": "a/b", "type": "blob"}]}'
    monkeypatch.undo()
    monkeypatch.setattr(gh, "_run", lambda *a, **k: _Proc(body))
    assert gh.repo_paths("o/r", "main") == {"a/b"}


def test_repo_paths_is_none_when_truncated(monkeypatch):
    monkeypatch.undo()
    monkeypatch.setattr(gh, "_run", lambda *a, **k: _Proc('{"truncated": true, "tree": []}'))
    assert gh.repo_paths("o/r", "main") is None


def test_repo_paths_is_empty_for_an_empty_repo(monkeypatch):
    monkeypatch.undo()
    monkeypatch.setattr(gh, "_run", lambda *a, **k: _Proc(stderr="HTTP 409", returncode=1))
    assert gh.repo_paths("o/r", "main") == set()


def test_repo_paths_raises_on_rate_limit(monkeypatch):
    monkeypatch.undo()
    monkeypatch.setattr(gh, "_run", lambda *a, **k: _Proc(stderr="API rate limit exceeded", returncode=1))
    with pytest.raises(gh.GhError):
        gh.repo_paths("o/r", "main")
