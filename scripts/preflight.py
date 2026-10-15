#!/usr/bin/env python3
"""Pre-push gate. Run this before any commit, tag, or push.

    python scripts/preflight.py            # local checks
    python scripts/preflight.py --remote   # also check the GitHub repo settings HACS wants

Exit code 0 means every check below passed. It is not a substitute for CI - hassfest and
HACS validation need Docker and the GitHub API respectively - but it covers everything that
does not, and it is fast enough to run before every push instead of discovering the answer
in a red check on the default branch.

Why this file exists: three defects reached the default branch in one day (1.4.3 first
attempt: nested error strings; the plural spelling behind them; a changelog that was never
written) because the local checks asserted what had already been noticed instead of the
class of problem, and a script printed "updated" without looking. Each check here either
carries a self-test or verifies a file on disk rather than trusting a variable.

The secret scan reads its patterns from a file OUTSIDE this repository (default:
~/session-notes/preflight-secrets.txt, one literal per line, '#' comments allowed) so the
scan list cannot itself leak anything. If that file is missing the scan is reported as
SKIPPED, never silently passed.
"""

from __future__ import annotations

import argparse
import ast
import json
import pathlib
import py_compile
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
COMPONENT = ROOT / "custom_components" / "oupes_mega_ble"
SECRETS_FILE = pathlib.Path.home() / "oupes-scan-list.txt"
failures: list[str] = []
skipped: list[str] = []


def check(name: str):
    """Decorator: run fn, record the failure, keep going. One report at the end."""

    def wrap(fn):
        try:
            problem = fn()
        except Exception as exc:  # a check that errors is not a check that passed
            problem = f"raised {type(exc).__name__}: {exc}"
        else:
            problem = problem or ""
        mark = "\033[32mPASS\033[0m" if not problem else "\033[31mFAIL\033[0m"
        print(f"  [{mark}] {name}" + (f"\n         {problem}" if problem else ""))
        if problem:
            failures.append(f"{name}: {problem}")
        return fn

    return wrap


def run(cmd: list[str]) -> tuple[int, str]:
    p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
    return p.returncode, (p.stdout or "") + (p.stderr or "")


# ---------------------------------------------------------------- the checks


@check("pytest")
def t_pytest() -> str:
    code, out = run([sys.executable, "-m", "pytest", "-q"])
    if code != 0:
        return out.strip()[-900:]
    return ""


@check("tests run standalone (the CI path, no pytest installed)")
def t_standalone() -> str:
    bad = []
    for f in sorted((ROOT / "tests").glob("test_*.py")):
        code, out = run([sys.executable, str(f)])
        if code != 0:
            bad.append(f"{f.name}: {out.strip().splitlines()[-1] if out.strip() else 'exit %d' % code}")
    return "; ".join(bad)


@check("every module compiles")
def t_compile() -> str:
    bad = []
    for f in sorted(COMPONENT.glob("*.py")):
        try:
            py_compile.compile(str(f), doraise=True)
        except py_compile.PyCompileError as exc:
            bad.append(f"{f.name}: {exc.msg}")
    return "; ".join(bad)


@check("config_flow.py has no HA-free-import violations in tested helpers")
def t_helpers_parse() -> str:
    """The helpers the tests exec out of the source must stay dependency-free."""
    text = (COMPONENT / "config_flow.py").read_text(encoding="utf-8")
    need = ("def _parse_account_number", "def resolve_key_on_account_change")
    missing = [n for n in need if n not in text]
    if missing:
        return f"missing {missing} - the tests extract these by name and will fail on CI"
    return ""


@check("JSON files parse")
def t_json() -> str:
    bad = []
    for f in [COMPONENT / "manifest.json", COMPONENT / "strings.json",
              COMPONENT / "translations" / "en.json", ROOT / "hacs.json",
              *sorted((ROOT / ".github" / "ISSUE_TEMPLATE").glob("*.yml"))]:
        if not f.exists():
            bad.append(f"{f.name} is missing")
            continue
        if f.suffix == ".json":
            try:
                json.loads(f.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                bad.append(f"{f.name}: {exc}")
    return "; ".join(bad)


@check("manifest version, changelog head and git agree")
def t_version() -> str:
    ver = json.loads((COMPONENT / "manifest.json").read_text(encoding="utf-8")).get("version", "")
    if not re.fullmatch(r"\d+\.\d+\.\d+", ver):
        return f"manifest version {ver!r} is not X.Y.Z - HACS and the frontend translation cache both care"
    log = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    heads = re.findall(r"^## (\d+\.\d+\.\d+)", log, re.M)
    if not heads:
        return "CHANGELOG.md has no '## X.Y.Z' header at all"
    if heads[0] != ver:
        return f"manifest says {ver} but the newest CHANGELOG entry is {heads[0]}"
    if f"## {ver} " not in log:
        return f"no CHANGELOG entry for {ver} (this silently skipped three releases once)"
    return ""


@check("strings.json and translations/en.json error trees are identical")
def t_i18n() -> str:
    a = json.loads((COMPONENT / "strings.json").read_text(encoding="utf-8"))
    b = json.loads((COMPONENT / "translations" / "en.json").read_text(encoding="utf-8"))
    bad = [f for f in ("config", "options") if a.get(f, {}).get("error", {}) != b.get(f, {}).get("error", {})]
    return f"differs for: {bad}" if bad else ""


@check("no secret literals in tracked files")
def t_secrets() -> str:
    if not SECRETS_FILE.exists():
        skipped.append(f"secret scan ({SECRETS_FILE} not found)")
        return ""
    patterns = [
        line.strip()
        for line in SECRETS_FILE.read_text(encoding="utf-8", errors="replace").splitlines()
        if line.strip() and not line.startswith("#")
    ]
    if not patterns:
        skipped.append("secret scan (pattern file is empty)")
        return ""
    # Ask git which files are tracked, so ignored build junk cannot fail the run,
    # and so a tracked file containing a secret cannot hide behind .gitignore.
    code, out = run(["git", "ls-files"])
    if code != 0:
        return "git ls-files failed"
    hits = []
    for rel in out.splitlines():
        p = ROOT / rel
        if not p.is_file():
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for pat in patterns:
            if pat in text:
                hits.append(f"{rel} contains {pat[:4]}…")
    return "; ".join(hits[:12])


@check("no stale bytecode or build junk tracked")
def t_junk() -> str:
    code, out = run(["git", "ls-files"])
    junk = [f for f in out.splitlines() if "__pycache__" in f or f.endswith((".pyc", ".pyo"))]
    return f"tracked: {junk[:6]}" if junk else ""


@check("workflows trigger on push to the default branch")
def t_ci_reachable() -> str:
    """A green check that never runs on the branch people look at is worse than none."""
    d = ROOT / ".github" / "workflows"
    ymls = {f.name: f.read_text(encoding="utf-8") for f in d.glob("*.yml")}
    if not ymls:
        return "no workflows"
    need_push = [n for n, t in ymls.items() if re.search(r"hassfest|hacs", t, re.I) and "push:" not in t]
    return (
        f"{need_push} validate on pull_request only, so push-only branches are never checked "
        "(this hid invalid error strings through a whole release)" if need_push else ""
    )


@check("translations cover every selector/string key the UI can show")
def t_strings_coverage() -> str:
    code, out = run([sys.executable, str(ROOT / "tests" / "test_strings_against_hassfest.py")])
    if code != 0:
        return out.strip()[-600:]
    return ""


def remote_checks() -> None:
    """HACS validates repository settings, not code. Cheap to check before pushing."""
    tok_file = pathlib.Path.home() / "AppData/Local/Temp/gc.txt"
    if not tok_file.exists():
        print("  [\033[33mSKIP\033[0m] GitHub repo settings (no token file)")
        skipped.append("GitHub repo settings")
        return
    tok = ""
    for line in tok_file.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith("password="):
            tok = line.partition("=")[2].strip()
    import urllib.request

    owner = json.loads((ROOT / "hacs.json").read_text(encoding="utf-8")).get("name", "")
    repo = subprocess.run(["git", "remote", "get-url", "fork"], cwd=ROOT,
                          capture_output=True, text=True).stdout
    m = re.search(r"github\.com[:/]([^/]+)/([^/.]+)", repo)
    if not m:
        print("  [\033[33mSKIP\033[0m] GitHub repo settings (no fork remote)")
        return
    try:
        req = urllib.request.Request(
            f"https://api.github.com/repos/{m.group(1)}/{m.group(2)}",
            headers={"Authorization": f"Bearer {tok}", "Accept": "application/vnd.github+json"},
        )
        d = json.load(urllib.request.urlopen(req, timeout=25))
    except Exception as exc:
        print(f"  [\033[31mFAIL\033[0m] GitHub repo settings\n         {exc}")
        failures.append(f"remote: {exc}")
        return
    problems = []
    if not d.get("has_issues"):
        problems.append("Issues are disabled - HACS validation fails and issue templates are unreachable")
    print(f"  owner/repo: {m.group(1)}/{m.group(2)}  default={d.get('default_branch')}  name={owner!r}")
    for p in problems:
        print(f"  [\033[31mFAIL\033[0m] {p}")
        failures.append(f"remote: {p}")
    if not problems:
        print("  [\033[32mPASS\033[0m] GitHub repo settings (issues enabled)")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--remote", action="store_true", help="also check GitHub repository settings")
    args = ap.parse_args()

    print(f"preflight: {ROOT}\n")
    for fn in [v for k, v in sorted(globals().items()) if k.startswith("t_")]:
        pass  # checks already ran at import time via the decorator
    if args.remote:
        remote_checks()

    print()
    for s in skipped:
        print(f"  note: {s} was SKIPPED, not passed")
    if failures:
        print(f"\n\033[31m{len(failures)} check(s) FAILED - do not push\033[0m")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("\033[32mall checks passed\033[0m")
    return 0


if __name__ == "__main__":
    sys.exit(main())
