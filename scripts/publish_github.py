#!/usr/bin/env python3
"""Publish the verified local repository after `gh auth login` (never takes a token)."""
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def run(*args, capture=False):
    return subprocess.run(args, cwd=ROOT, check=True, text=True, capture_output=capture).stdout


def main():
    if subprocess.run(["gh", "auth", "status"], cwd=ROOT).returncode:
        raise SystemExit("GITHUB_AUTH_REQUIRED: gh auth login --hostname github.com --web --git-protocol https")
    run(sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v")
    username = json.loads(run("gh", "api", "user", capture=True))["login"]
    remote = subprocess.run(["git", "remote", "get-url", "origin"], cwd=ROOT, capture_output=True, text=True)
    if remote.returncode:
        run("gh", "repo", "create", "proxy-rule-sets", "--public", "--source", str(ROOT), "--remote", "origin")
    info = json.loads(run("gh", "repo", "view", "--json", "nameWithOwner,visibility,owner,url", capture=True))
    if info["owner"]["login"].lower() != username.lower() or info["visibility"] != "PUBLIC":
        raise SystemExit("Refusing to publish: origin must be your own PUBLIC repository")
    branch = run("git", "branch", "--show-current", capture=True).strip()
    raw = f"https://raw.githubusercontent.com/{info['nameWithOwner']}/{branch}"
    run(sys.executable, "scripts/update_rules.py", "--offline", "--raw-base", raw)
    run(sys.executable, "scripts/build_extensions.py")
    run(sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v")
    run("node", "--test", "tests/extensions.test.cjs")
    run("git", "add", "--all")
    if subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=ROOT).returncode:
        run("git", "commit", "-m", "docs: set published rule set URLs")
    run("git", "push", "--set-upstream", "origin", branch)
    print(info["url"])
    print(raw)


if __name__ == "__main__":
    main()
