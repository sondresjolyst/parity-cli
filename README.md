# parity-cli

See and fix drift in `dependabot.yml`, `CODEOWNERS` and shared workflows across
all your GitHub repos.

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
parity diff <repo>            # unified diff for one repo
parity tui                    # interactive dashboard
parity apply                  # branch + commit + PR for every drifted repo
parity apply -r garge-api -y  # limit to one repo, skip confirmation
parity apply --no-pr          # push branch only
```

Each repo's languages are detected and mapped to templates. `apply` opens one PR
per repo; the commit message names what changed.

### TUI keys

| key | action |
|-----|--------|
| `r` | rescan |
| `space` | select/deselect repo |
| `d` / `enter` | show diff |
| `o` | open the repo's parity PR |
| `a` | apply selected |
| `q` | quit |

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

```yaml
owner: sondresjolyst
templates_dir: templates
workflows_dir: .github/workflows

language_threshold: 0.10       # ignore languages below this share of the repo
include_archived: false
include_forks: false
branch_name: parity/sync-standards

workflows:
  dependency-review.yml: [all] # filename -> languages (["all"] = every repo)

vars:
  owner: "@sondresjolyst"

# repos_include: []            # only these repos (empty = all)
# repos_exclude: []
# language_map:                # override GitHub language -> template dir
#   TypeScript: node
```

## Tests

```sh
uv run --native-tls pytest -q
```
