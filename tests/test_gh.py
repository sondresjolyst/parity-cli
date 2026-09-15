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
