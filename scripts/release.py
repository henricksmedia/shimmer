"""Make a Shimmer release: the steps in docs/RELEASING.md, in one command.

    python scripts/release.py 2.3.4 "Start screen and start.bat fix"
    python scripts/release.py 2.3.4 "Start screen and start.bat fix" --dry-run

It checks, then:
  1. sets the version in shimmer/__init__.py, README.md and
     docs/GETTING-STARTED.md, and turns [Unreleased] in CHANGELOG.md into
     the new version with today's date;
  2. commits "X.Y.Z: <summary>" and pushes it to main on GitHub;
  3. tags vX.Y.Z and publishes the GitHub release, with the notes taken
     from the changelog;
  4. brings the everyday folder (the checkout on main) up to the release.

Run the tests first (step 2 in docs/RELEASING.md); this script does not.
"""
import argparse
import datetime
import io
import os
import re
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def run(*cmd, cwd=ROOT, check=True):
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if check and r.returncode != 0:
        sys.exit(f"FAILED: {' '.join(cmd)}\n{r.stdout}{r.stderr}")
    return r.stdout.strip()


def read(rel):
    return io.open(os.path.join(ROOT, rel), encoding="utf-8").read()


def write(rel, text):
    # The repo is LF only.
    io.open(os.path.join(ROOT, rel), "w", encoding="utf-8", newline="\n").write(text)


def sub_once(pattern, repl, text, what):
    new, n = re.subn(pattern, repl, text)
    if n == 0:
        sys.exit(f"FAILED: could not find {what}")
    return new


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("version", help="the new version, e.g. 2.3.4")
    ap.add_argument("summary", help='a few words for the commit, e.g. "Start screen"')
    ap.add_argument("--dry-run", action="store_true", help="check and show, change nothing")
    a = ap.parse_args()

    new = a.version
    if not re.fullmatch(r"\d+\.\d+\.\d+", new):
        sys.exit("The version must look like 2.3.4.")
    init = read("shimmer/__init__.py")
    old = re.search(r'__version__ = "([^"]+)"', init).group(1)
    as_tuple = lambda v: tuple(int(x) for x in v.split("."))
    if as_tuple(new) <= as_tuple(old):
        sys.exit(f"{new} is not newer than {old}.")
    today = datetime.date.today().isoformat()

    # ── Checks ────────────────────────────────────────────────────────────
    dirty = [ln for ln in run("git", "status", "--porcelain").splitlines() if not ln.startswith("??")]
    if dirty:
        sys.exit("Commit or set aside these changes first:\n" + "\n".join(dirty))
    run("git", "fetch", "-q", "origin")
    if subprocess.run(["git", "merge-base", "--is-ancestor", "origin/main", "HEAD"], cwd=ROOT).returncode:
        sys.exit("origin/main has commits this branch lacks. Merge it first.")
    if run("git", "tag", "-l", f"v{new}"):
        sys.exit(f"The tag v{new} already exists.")
    log = read("CHANGELOG.md")
    head = "## [Unreleased]\n"
    start = log.index(head) + len(head)
    unreleased = log[start:log.index("\n## [", start)].strip()
    if not unreleased:
        sys.exit("CHANGELOG.md has nothing under [Unreleased].")

    print(f"Release {old} -> {new} ({today}): {a.summary}\n")
    print("Notes (from CHANGELOG.md):\n" + unreleased + "\n")
    if a.dry_run:
        print("Dry run: nothing changed.")
        return

    # ── 1. Version and changelog ──────────────────────────────────────────
    write("shimmer/__init__.py", init.replace(f'__version__ = "{old}"', f'__version__ = "{new}"'))
    readme = read("README.md")
    write("README.md", sub_once(rf"Get {re.escape(old)} the same way", f"Get {new} the same way",
                                readme, "README's 'Get X the same way' line"))
    gs = read("docs/GETTING-STARTED.md")
    gs = sub_once(r"Version \S+ came out on \d{4}-\d{2}-\d{2}\.",
                  f"Version {new} came out on {today}.", gs, "GETTING-STARTED's release date line")
    gs = gs.replace(f"what-is-not-in-{old.replace('.', '')}-yet", f"what-is-not-in-{new.replace('.', '')}-yet")
    gs = gs.replace(old, new)
    write("docs/GETTING-STARTED.md", gs)
    write("CHANGELOG.md", log[:start] + f"\n## [{new}] — {today}\n" + log[start:])

    # ── 2. Commit and push to main ────────────────────────────────────────
    run("git", "add", "shimmer/__init__.py", "README.md", "docs/GETTING-STARTED.md", "CHANGELOG.md")
    run("git", "commit", "-q", "-m", f"{new}: {a.summary}")
    run("git", "push", "-q", "origin", "HEAD:main")
    print("Pushed to main:", run("git", "log", "--oneline", "-1"))

    # ── 3. Tag and GitHub release ─────────────────────────────────────────
    run("git", "tag", "-a", f"v{new}", "-m", f"Shimmer {new}")
    run("git", "push", "-q", "origin", f"v{new}")
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8", newline="\n") as f:
        f.write(unreleased + "\n")
        notes = f.name
    try:
        url = run("gh", "release", "create", f"v{new}", "--title", f"Shimmer {new}", "--notes-file", notes)
    finally:
        os.unlink(notes)
    print("Released:", url)

    # ── 4. The everyday folder (the checkout on main) ─────────────────────
    wt, everyday = None, None
    for ln in run("git", "worktree", "list", "--porcelain").splitlines():
        if ln.startswith("worktree "):
            wt = ln[len("worktree "):]
        elif ln == "branch refs/heads/main":
            everyday = wt
    if not everyday:
        print("No checkout on main here: nothing to bring up to date.")
    elif run("git", "status", "--porcelain", "--untracked-files=no", cwd=everyday):
        print(f"{everyday} has changes of its own: left alone. Its start.bat updates it.")
    else:
        run("git", "fetch", "-q", "origin", cwd=everyday)
        run("git", "merge", "-q", "--ff-only", "origin/main", cwd=everyday)
        print(f"{everyday} is now at", run("git", "log", "--oneline", "-1", cwd=everyday))

    print("\nNext: check CI (step 5 in docs/RELEASING.md).")


if __name__ == "__main__":
    main()
