# Release checklist

The failure this checklist exists to prevent happened for real: **v1.4.6 and
v1.4.7 were tagged and pushed, tests were green, and users still saw v1.4.5** -
because `git push --follow-tags` publishes the *tag*, while GitHub's Releases
box and HACS "custom repository" installs (which default to tracking **Last
release**) read the *release object*. Tags do not create release objects. The
gap was invisible from the command line.

Since 2026-10-15 the release object is created **automatically** by
[`release-on-tag.yml`](../.github/workflows/release-on-tag.yml): pushing a
`v*` tag creates (or leaves alone, if it already exists) the GitHub Release,
using this version's `CHANGELOG.md` section as the release notes. There is no
manual GitHub step to forget. There is still an order to get right locally:

## 1. Prepare

- [ ] `py -m pytest tests/ -q` - all green (currently 177).
- [ ] Bump `version` in `custom_components/oupes_mega_ble/manifest.json`.
- [ ] Add the `## X.Y.Z - YYYY-MM-DD` section to `CHANGELOG.md`, **above** the
      previous one. The release-on-tag workflow lifts this section verbatim
      into the GitHub Release; if it is missing, the release says so and CI
      logs a warning (a public nag, deliberately).
- [ ] User-visible field/label changes: update `strings.json` **and** copy it
      byte-identical to `translations/en.json`, plus the README where the
      field is documented (Tuning table). The repo's own guard tests fail
      otherwise.
- [ ] Commit everything; the tree must be clean before tagging.

## 2. Publish

```bash
git tag vX.Y.Z                    # lightweight is fine; the workflow handles it
git push fork release --follow-tags
git push fork vX.Y.Z              # --follow-tags only pushes *annotated* tags
```

## 3. Verify the invariant (30 seconds, non-optional)

The release is not done when the push succeeds; it is done when the *API*
agrees:

```bash
curl -s https://api.github.com/repos/bandit8623/oupes-mega-ble-hass/releases/latest \
  | grep '"tag_name"'            # must print vX.Y.Z
```

If it prints the previous version, either the workflow job failed (check the
Actions tab) or it raced the API; both are fixed by re-running the job, and
the checklist item above means the notes will be there either way.

## 4. Field confirmation

- HACS (as a logged-in user or with your friend): the new version offered
  within ~5 minutes, or after *Custom repositories → reload*.
- Live HA box: version in the integration manifest matches, log quiet for a
  few minutes.

## Notes

- The workflow is idempotent by design: a manually created release (the
  fallback below, or a hotfix from the web UI) is detected and left alone.
- Fallback if Actions is disabled: create the release in the GitHub web UI
  from the tag, pasting the `CHANGELOG.md` section - the workflow then skips.
- `docs/` keeps longer-form protocol notes; this file is the only release
  procedure. If they ever disagree, this file wins.
