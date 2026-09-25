# Making a release

How a new version of Shimmer goes out. Most of it is one command,
`scripts/release.py`. The steps around it are below.

**Words used here**

- **main**: the branch on GitHub that users get. `start.bat` and
  `start.sh` update a git copy to the newest release on main.
- **Release**: a version tag (such as `v2.3.4`) plus a page on the GitHub
  Releases list with its notes.
- **The everyday folder**: the checkout on main that is used day to day.
  Test copies run from other folders with `start-test.bat`.

## Version numbers

`MAJOR.MINOR.PATCH`, as in [Semantic Versioning](https://semver.org/).

- **Patch** (2.3.3 → 2.3.4): fixes and small changes to screens or sound.
- **Minor** (2.3.x → 2.4.0): a new feature, such as a new detector or tool.
- **Major** (2.x → 3.0.0): a rebuild, or a change that breaks saved settings
  or the API.

## Steps

**1. Write the changelog.** Every change goes under `## [Unreleased]` in
`CHANGELOG.md`, in `### Added`, `### Changed` or `### Fixed`, as you make
it. Plain words, 8th-grade level: what the user sees or hears, not the
code. These lines become the release notes word for word.

**2. Run the tests.** All of them, from the Shimmer folder:

```bash
.venv/Scripts/python.exe -m pytest -q tests
```

Nothing may fail. It takes about five minutes.

**3. Check first, with a dry run.** It changes nothing. It shows the old and
new version and the release notes.

```bash
.venv/Scripts/python.exe scripts/release.py 2.3.4 "Start screen and start.bat fix" --dry-run
```

It stops if:
- there are changes that are not committed;
- GitHub's main has commits this branch lacks (merge them first);
- the tag already exists;
- `[Unreleased]` is empty.

**4. Release.** The same command without `--dry-run`:

```bash
.venv/Scripts/python.exe scripts/release.py 2.3.4 "Start screen and start.bat fix"
```

In order, it:
1. sets the version in `shimmer/__init__.py`, `README.md` and
   `docs/GETTING-STARTED.md` (its title, date line and section links);
2. turns `[Unreleased]` into `[2.3.4] — <today>` in `CHANGELOG.md`;
3. commits `2.3.4: <summary>` and pushes it to main;
4. tags `v2.3.4` and publishes the GitHub release "Shimmer 2.3.4", with the
   notes from the changelog;
5. brings the everyday folder up to the release, if it has no changes of
   its own.

**5. Check CI.** The push to main starts the tests on GitHub: Linux (Python
3.11 and 3.12), Windows with ffmpeg, and updating a 1.1.1 install.

```bash
gh run list --branch main --limit 1
```

```bash
gh run watch <run id> --exit-status
```

If a job fails, fix it and make a patch release. Do not move or delete a
tag that users may already have.

## Rules

- Commit messages are short and plain, with no Co-Authored-By lines.
- Release only when asked. A commit on a branch is not a release.
- Never put personal paths or names in the repo. The script finds the
  everyday folder from `git worktree list`.
