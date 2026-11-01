# parity-cli

See and fix drift in `dependabot.yml`, `renovate.json`, `CODEOWNERS` and shared
workflows across all your GitHub repos.

This repo is the config: `parity.yml`, `templates/` and `.github/` define what
every managed repo should look like. Edit those, then run the commands below.

## Install

```sh
uv sync --native-tls
```

## Usage

```sh
parity status                 # drift table across all repos
parity prs                    # list open PRs parity has created
parity settings               # repo settings drift (add --apply to fix)
parity diff <repo>            # unified diff for one repo
parity tui                    # interactive dashboard
parity apply                  # branch + commit + PR for every drifted repo
parity apply -r garge-api -y  # limit to one repo, skip confirmation
parity apply --no-pr          # push branch only
```

Each repo's languages are detected and mapped to templates. `apply` opens one PR
per repo; the commit message names what changed.

### TUI keys

| key           | action                     |
| ------------- | -------------------------- |
| `r`           | rescan                     |
| `space`       | select/deselect repo       |
| `d` / `enter` | show diff                  |
| `o`           | open the repo's parity PR  |
| `s`           | repo settings drift screen |
| `a`           | apply selected             |
| `q`           | quit                       |

## Layout

```text
parity.yml                     # config
templates/
  _base/CODEOWNERS
  _actions/dependabot.fragment.yml
  python/ node/ dotnet/ docker/ uv/
    dependabot.fragment.yml
    files/**                   # optional extra files, mapped to repo paths
.github/workflows/             # workflow templates
```

## Config (`parity.yml`)

Owner mode (default, backward compatible):

```yaml
owner: sondresjolyst
discovery_mode: owner         # optional; default is owner
templates_dir: templates
workflows_dir: .github/workflows

language_threshold: 0.10       # ignore languages below this share of the repo
include_archived: false
include_forks: false
branch_name: parity/sync-standards

workflows:
  dependency-review.yml: [all] # filename -> languages (["all"] = every repo)

settings:                      # managed repo settings (parity settings)
  delete_branch_on_merge: true
  squash_merge_commit_title: PR_TITLE
  squash_merge_commit_message: PR_BODY
  has_wiki: false
  allow_update_branch: true
  actions_default_workflow_permissions: read
  actions_can_approve_pull_request_reviews: true
  dependabot_alerts: true
  dependabot_security_updates: true

vars:
  owner: "@sondresjolyst"

# repos_include: []            # only these repos (empty = all)
# repos_exclude: []
# language_map:                # override GitHub language -> template dir
#   TypeScript: node
```

Team mode:

```yaml
discovery_mode: team
teams:
  - my-org/platform-team
  - my-org/reliability

templates_dir: templates
workflows_dir: .github/workflows

vars:
  owner: "@my-org/platform-team" # optional override for CODEOWNERS/templates
```

- `discovery_mode` accepts `owner` or `team`.
- `owner` is required in owner mode.
- `teams` is required in team mode and uses `org/team_slug` entries.
- In team mode, if `vars.owner` is omitted, parity defaults `${owner}` to the
  first configured team as `@org/team_slug` when rendering templates (including
  the default `CODEOWNERS` template).

## Dependency updates

Dependabot is the default, so existing configs keep working unchanged. To move
repos to Renovate:

```yaml
dependency_manager: dependabot      # default for every repo
dependency_manager_repos:           # per-repo override, either direction
  my-repo: renovate
renovate_preset: github>my-org/renovate-config  # required when Renovate is used
renovate_remove_codeowners: false   # true also removes CODEOWNERS from Renovate repos

workflows:
  dependabot-title.yml:
    languages: [all]
    manager: dependabot             # only for repos using this manager
```

- A Renovate repo gets a `renovate.json` that extends the preset. `apply` removes
  its `dependabot.yml`.
- Install the Renovate app on a repo before `apply` removes its `dependabot.yml`.
- A `renovate.json` matches as long as it extends the preset, so a repo can add
  its own rules. If the preset is missing, `apply` adds it and keeps the rest.
- A repo with an invalid `renovate.json`, or with its Renovate config in another
  location, shows as an error and is not changed.
- A Dependabot repo's `renovate.json` is left alone. Remove it by hand when moving
  a repo back, or both tools open PRs.
- Only set `renovate_remove_codeowners` where branch protection does not require
  code owner review.

## Tests

```sh
uv run --native-tls pytest -q
```
