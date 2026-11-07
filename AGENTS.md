<!--
SPDX-FileCopyrightText: 2026 Stephan Strittmatter
SPDX-License-Identifier: MIT
-->

# ptzsim — Agent Instructions

Command-line PTZ camera simulator (ONVIF, VISCA, Pelco-D, NDI) for testing PTZ clients
without a real camera.
User-facing docs are in [README.md](README.md); keep it in sync with every change to
options, ports or commands.

## Tooling: uv

The project is managed with [uv](https://docs.astral.sh/uv/). Do not use `pip` or a
hand-made venv.

| Command | Purpose |
|---------|---------|
| `uv sync` | Create/update `.venv` from `uv.lock` (includes the `dev` group) |
| `uv run pytest` | Run the test suite |
| `PTZSIM_ONVIF_CLIENT=1 uv run --group onvif-client pytest` | Also run the test against the real ONVIF client (`onvif-zeep-async`) |
| `uv run --extra ndi pytest` | Also run the real NDI round trip (needs the NDI runtime) |
| `uv run ptzsim serve --onvif` | Start the simulator with ONVIF enabled |
| `uv add <pkg>` / `uv add --group dev <pkg>` | Add a dependency; commit `pyproject.toml` and `uv.lock` together |

### Verification (must pass after every change)

```sh
uv run pytest
```

Run the `onvif-client` variant as well whenever `ptzsim/onvif.py` changes.

## Releases

Versions and `CHANGELOG.md` are managed by [Release Please](https://github.com/googleapis/release-please)
(`release-please-config.json`, `.release-please-manifest.json`). Commit messages must
follow [Conventional Commits](https://www.conventionalcommits.org/) (`feat:`, `fix:`,
`docs:`, …; `!` or `BREAKING CHANGE:` for breaking changes) — they decide the next version.
Never bump the version in `pyproject.toml` or `ptzsim/__init__.py` by hand.

### Pull request titles and commit messages

Release Please reads the commit messages on `main`. With a squash merge the PR title
becomes the commit message; with a merge commit the PR's own commits are read. So
**both the PR title and every commit on the branch** must use this format:

```text
<type>[optional scope][!]: <description>
```

- `type` is one of the types in `release-please-config.json`. Types with a visible
  changelog section trigger a release; hidden types neither trigger a
  release nor appear in `CHANGELOG.md`:

  | Type | Use for | Version effect | Changelog |
  |------|---------|----------------|-----------|
  | `feat` | new user-visible feature | minor | Features |
  | `fix` | bug fix | patch | Bug Fixes |
  | `perf` | performance improvement | patch | Performance |
  | `docs` | documentation only | patch | Documentation |
  | `refactor` | code change without behaviour change | none | hidden |
  | `test` | tests only | none | hidden |
  | `ci` | workflows, release tooling | none | hidden |
  | `chore` | dependencies, housekeeping | none | hidden |

- `scope` is optional, lowercase, and names the affected area, preferably a module or
  protocol: `onvif`, `visca`, `ndi`, `tui`, `cli`, `state`, `website`, `deps`.
- `description`: imperative mood, lowercase start, no trailing period, at most ~72
  characters for the whole title; written in English. It becomes the changelog entry,
  so describe the effect for users, not the implementation
  (`fix(onvif): report zoom position in GetStatus`, not `fix: update onvif.py`).
- Breaking changes: add `!` after type/scope (`feat(cli)!: rename --port to --visca-port`)
  and explain the migration in a `BREAKING CHANGE: …` footer in the commit or squash
  body. While the version is below 1.0.0 (`bump-minor-pre-major`), a breaking change
  bumps the minor version instead of the major.
- One PR, one type: if a PR mixes a feature and an unrelated fix, split it. Pick the
  type with the largest version effect that the change really has; do not label a
  feature `chore` or a fix `docs` to avoid a release.
- Never use titles like `Update README`, `WIP`, `Fix stuff` or the default branch name;
  rename the PR before it is merged if needed.
- Do not edit `CHANGELOG.md` or the Release Please PR (`chore(main): release …`) by hand.

The workflow `.github/workflows/pr-title.yml` (check "Conventional Commits") enforces
these rules on every PR with `scripts/check_conventional_commits.py`, which reads the
allowed types from `release-please-config.json`. Check locally before pushing:

```sh
git log --no-merges --format=%s origin/main..HEAD | python3 scripts/check_conventional_commits.py -
```

If a commit fails, reword it (`git commit --amend` or an interactive rebase) before
the PR is merged; a renamed PR title re-runs the check automatically.

- `.github/workflows/ci.yml` — tests on Python 3.8 and 3.13, builds the release artifacts.
- `.github/workflows/pr-title.yml` — Conventional Commits gate for PR title and commits.
- `.github/workflows/release-please.yml` — maintains the release PR (and its `uv.lock`);
  merging it tags the release and attaches wheel, sdist and `ptzsim.pyz` built by
  `scripts/build-release.sh`. PyPI upload runs only when the repository variable
  `PYPI_PUBLISH` is `true` (requires a PyPI trusted publisher, environment `pypi`).

## Constraints

- **Runtime is standard library only.** ONVIF, VISCA and Pelco-D must keep working with
  plain `python3 -m ptzsim` and no installed packages. Third-party packages go into the
  `ndi` extra (runtime, optional) or a dependency group (dev/test only).
- `requires-python = ">=3.8"`: no syntax or stdlib APIs newer than 3.8
  (`from __future__ import annotations` is used for type hints).
- Tests that need optional packages must skip cleanly (`pytest.importorskip` or an
  env-var `skipif`), so `uv run pytest` passes on a bare setup.

## Architecture

- `ptzsim/state.py` — `CameraState`: the shared camera model (position, motion at motor
  speed, presets) in VISCA units, with the position limits as module constants.
- `ptzsim/protocol.py` — plugin interface for control protocols: `ProtocolPlugin` /
  `PortPlugin`, `ServeContext`, `Endpoint`, the registry (`register`, `plugins`,
  `selected`) and loading of in-tree (`EXTRA_MODULES`) and entry-point plugins
  (group `ptzsim.protocols`). `cli.py` builds the `serve` options and start-up from it.
- `ptzsim/builtin_protocols.py` — the plugins for VISCA (Sony IP, TCP, UDP, pty), ONVIF
  and NDI; registration order is the order in `--help` and the dashboard title.
- `ptzsim/testing.py` — `serve(*argv)` starts plugins like `ptzsim serve` for
  end-to-end tests; `free_port()`.
- `ptzsim/visca.py` — `ViscaCamera`: VISCA command parser on top of `CameraState`; the
  other protocols drive the same `ViscaCamera` instance.
- `ptzsim/pelco.py` — `PelcoCamera`: Pelco-D parser (7-byte frames with checksum, ACK
  replies) driving the same `ViscaCamera`; used by the `--pelco-d` plugin.
- `ptzsim/onvif.py` — `OnvifCamera`: SOAP over HTTP (Device, Media, PTZ services,
  WS-Security digest auth) and the WS-Discovery responder on UDP 3702. Converts between
  VISCA units and the ONVIF generic spaces (pan/tilt −1…1, zoom 0…1).
- `ptzsim/transports.py` — Sony VISCA over IP (UDP 52381), raw VISCA over TCP/UDP, serial
  via pseudo terminal (`PtyPort` takes any `process(packet, send)` handler plus a frame
  `split`, e.g. VISCA packets or Pelco-D frames).
- `ptzsim/ndi.py` — optional NDI source with PTZ control and a rendered test picture.
- `ptzsim/display.py` — renders the dashboard (`render`), read-only view and `--no-tui` log.
- `ptzsim/tui.py` — interactive keyboard UI. `TuiController` maps keys to `CameraState`
  actions and is curses-free so it can be unit-tested with a fake clock; only
  `interactive()` touches curses. Terminals send no key-release events, so jogs stop
  after `JOG_TIMEOUT` without key repeat.
- `ptzsim/viewfinder.py` — text-mode camera picture for the TUI (`render_view`;
  `render_picture` also returns the colour of every cell), same scene geometry as
  `ndi.SceneRenderer` (60° FOV at 1×); keep both in sync. Grid lines use half-open
  cells (`_on_line`) so each line is drawn exactly once.
- `ptzsim/scenery.py` — landmarks at fixed pan/tilt (text art, colours for terminal and
  NDI), drawn by both renderers. One art character is `px` degrees wide and twice as
  high; when zoomed in, solid characters fill, lines stretch and text is drawn once.
  `scripts/scene_docs.py` generates the landmark tables in README.md and
  `docs/scene.md` and the images in `docs/public/images/scene/`; after changing
  the scene run `uv run --with numpy python scripts/scene_docs.py --images`
  (`tests/test_scene_docs.py` fails while the tables are out of date).
- `ptzsim/cli.py` — `serve` and `send`; picks TUI, `--view-only` dashboard or `--no-tui`.

## ONVIF interoperability

Keep ONVIF discovery, PTZ motion, status and preset operations compatible with
clients when changing `ptzsim/onvif.py`. Supported operations and limitations are
listed in [README.md](README.md#onvif-scope).

## Adding a protocol

New protocols are plugins; follow [docs/adding-a-protocol.md](docs/adding-a-protocol.md)
(step by step, with a tested example). Do not add protocol options or start-up code to
`cli.py` directly. `tests/test_protocol.py` runs the guide's example code, so keep the
example working when the interface changes, and update the guide with it.

## Agent skills

`.agents/skills/` ships [Agent Skills](https://agentskills.io) that other projects install
(`scripts/install-skills.sh`, see the README section "Agent skills") to implement
reference-conformant camera interfaces. Keep every `SKILL.md` self-contained (link only
inside `.agents/skills/`, refer to this repo by absolute GitHub URLs) with valid
frontmatter: `name` matches the directory (lowercase-hyphen, ≤64 chars), `description`
≤1024 chars, SKILL.md ≤500 lines with details in `references/` — `tests/test_skills.py`
enforces this. Bundled `scripts/*.py` must stay Python 3.8+ standard-library only.
The documentation site has a page for them, `docs/skills.md` (register new pages in
`docs/.vitepress/config.mjs`; `docs/tests/site.test.mjs` builds the site and must pass).
