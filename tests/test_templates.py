import yaml

from parity_cli import templates
from parity_cli.model import Kind


def test_dependabot_merges_ecosystems(config):
    files = templates.desired_files(["python", "node"], config)
    dependabot = next(f for f in files if f.kind is Kind.DEPENDABOT)
    doc = yaml.safe_load(dependabot.content)
    ecosystems = {u["package-ecosystem"] for u in doc["updates"]}
    assert ecosystems == {"github-actions", "pip", "npm"}
    assert doc["version"] == 2


def test_dependabot_carries_house_settings(config):
    files = templates.desired_files(["python"], config)
    doc = yaml.safe_load(next(f for f in files if f.kind is Kind.DEPENDABOT).content)
    pip = next(u for u in doc["updates"] if u["package-ecosystem"] == "pip")
    assert pip["schedule"] == {"interval": "weekly", "day": "sunday"}
    assert pip["cooldown"] == {"default-days": 7}
    assert pip["commit-message"] == {"prefix": "deps(pip)"}


def test_codeowners_variable_substituted(config):
    files = templates.desired_files([], config)
    codeowners = next(f for f in files if f.kind is Kind.CODEOWNERS)
    assert codeowners.content.strip() == "* @sondresjolyst"


def test_workflow_included(config):
    files = templates.desired_files([], config)
    paths = {f.path for f in files if f.kind is Kind.WORKFLOW}
    assert ".github/workflows/dependency-review.yml" in paths


def test_public_repo_gets_dependency_review(config):
    paths = {f.path for f in templates.desired_files([], config, private=False)}
    assert ".github/workflows/dependency-review.yml" in paths


def test_private_repo_skips_dependency_review_keeps_others(config):
    paths = {f.path for f in templates.desired_files([], config, private=True)}
    assert ".github/workflows/dependency-review.yml" not in paths
    assert ".github/workflows/dependabot-title.yml" in paths


def test_self_reference_workflow_skipped_in_host_repo(config):
    host = {f.path for f in templates.desired_files(
        [], config, full_name="sondresjolyst/garge")}
    other = {f.path for f in templates.desired_files(
        [], config, full_name="sondresjolyst/garge-app")}
    assert ".github/workflows/dependabot-title.yml" not in host
    assert ".github/workflows/dependabot-title.yml" in other


def test_cpp_has_no_pip_entry(config):
    files = templates.desired_files(["cpp"], config)
    doc = yaml.safe_load(next(f for f in files if f.kind is Kind.DEPENDABOT).content)
    ecosystems = {u["package-ecosystem"] for u in doc["updates"]}
    assert ecosystems == {"github-actions"}
