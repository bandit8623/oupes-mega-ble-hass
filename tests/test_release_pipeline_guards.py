"""Guards for the release pipeline itself.

Why: v1.4.6 and v1.4.7 were tagged and pushed correctly, tests green, and
users still sat on v1.4.5 - `git push --follow-tags` creates a tag, but HACS
"custom repository" installs and GitHub's Releases box read the *release
object*, which tags do not create. The fix is a workflow that turns any pushed
`v*` tag into a GitHub Release, plus docs/RELEASING.md as the human checklist.

A fix that can be deleted without a test failing is not a fix. These tests
make the guardrails load-bearing: they assert the workflow exists, triggers on
version tags, has the permission to create releases, is idempotent, and that
every release tag in this repo actually has a CHANGELOG section - the same
section the automation pastes into the release notes.
"""

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = ROOT / ".github" / "workflows" / "release-on-tag.yml"
RELEASING = ROOT / "docs" / "RELEASING.md"
CHANGELOG = ROOT / "CHANGELOG.md"


def test_release_workflow_exists_and_triggers_on_version_tags():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert re.search(r'^\s*-\s*"v\*"', text, re.M), \
        "release-on-tag.yml must trigger on pushed v* tags"


def test_release_workflow_can_create_releases():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert re.search(r"^permissions:", text, re.M), \
        "workflow must declare explicit permissions"
    assert re.search(r"^\s*releases:\s*write\s*$", text, re.M), \
        "workflow needs releases:write or it silently fails on private runners"


def test_release_workflow_is_idempotent():
    """Re-runs and manual releases must not 409 or double-publish."""
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "/releases/tags/" in text, \
        "workflow must check for an existing release before creating one"


def test_changelog_and_tags_agree():
    """Every local release tag has a CHANGELOG section, and vice versa.

    The workflow degrades gracefully without one (it says so in the release
    and warns in CI), but a tag or an entry appearing without its twin is a
    process smell worth failing on at commit time, not on a public page.
    """
    try:
        out = subprocess.run(
            ["git", "tag", "--list", "v*"],
            cwd=ROOT, capture_output=True, text=True, check=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        import pytest
        pytest.skip("git tags unavailable (shallow clone / no git)")

    text = CHANGELOG.read_text(encoding="utf-8")
    entries = set(re.findall(r"^## (\d+\.\d+\.\d+) -", text, re.M))
    tags = {t.removeprefix("v") for t in out.split() if re.fullmatch(r"v\d+\.\d+\.\d+", t)}

    missing_entry = sorted(tags - entries)
    assert not missing_entry, (
        f"Tags with no CHANGELOG '## x.y.z' section: {missing_entry}. "
        "The GitHub Release for these would carry the automation's nag text."
    )
    missing_tag = sorted(entries - tags)
    assert not missing_tag, (
        f"CHANGELOG entries with no matching tag: {missing_tag}. "
        "Unreleased entries belong in the checklist's prepare step, not on main."
    )


def test_releasing_doc_presents_the_api_verification_step():
    """The bug was invisible from the command line; the doc must keep the
    'verify via the API' step that makes it visible."""
    text = RELEASING.read_text(encoding="utf-8")
    assert "releases/latest" in text, \
        "RELEASING.md must include the post-push API verification command"
    assert "git push fork v" in text, \
        "RELEASING.md must warn that --follow-tags does not push lightweight tags"
