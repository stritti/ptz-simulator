---
title: Agent skills
---

<!--
SPDX-FileCopyrightText: 2026 Stephan Strittmatter
SPDX-License-Identifier: MIT
-->

# Agent skills

ptzsim ships [Agent Skills](https://agentskills.io) — self-contained instruction
packages (a `SKILL.md` plus `references/` and `scripts/`) — that any project can
install, so its AI coding agent (Claude Code, GitHub Copilot, Vibe Code, Cursor, Codex,
…) implements a **reference-conformant PTZ camera interface** and validates it against
this simulator. The skills live in
[`.agents/skills/`](https://github.com/stritti/ptz-simulator/tree/main/.agents/skills)
in the repository; agents that scan `.agents/skills/` (GitHub Copilot, OpenAI Codex,
Mistral Vibe, …) pick them up in this repo directly.

## The skills

| Skill | What it teaches | Bundled files |
|---|---|---|
| [`ptz-reference-interface`](https://github.com/stritti/ptz-simulator/tree/main/.agents/skills/ptz-reference-interface) | Entry point: choose the protocol (comparison matrix, ports, official specs), implementation workflow, validation, documenting deviations | `references/protocol-selection.md` |
| [`visca-interface`](https://github.com/stritti/ptz-simulator/tree/main/.agents/skills/visca-interface) | VISCA over RS-232/422 and VISCA over IP (UDP 52381): framing, command/inquiry set, ACK/completion/error replies, the two command sockets, sequence numbers, value ranges | `references/visca-transports.md`, `references/visca-commands.md`, `scripts/visca_conformance.py` |
| [`onvif-ptz-interface`](https://github.com/stritti/ptz-simulator/tree/main/.agents/skills/onvif-ptz-interface) | ONVIF Profile S/T PTZ service: Device/Media/PTZ operations, generic coordinate spaces, SOAP 1.2 fault chains, WS-Discovery (UDP 3702), WS-Security UsernameToken PasswordDigest and HTTP digest auth | `references/onvif-services.md`, `references/onvif-spaces-faults-auth.md`, `references/soap-examples.md`, `scripts/onvif_conformance.py` |
| [`pelco-d-interface`](https://github.com/stritti/ptz-simulator/tree/main/.agents/skills/pelco-d-interface) | Pelco-D serial over RS-485/RS-422: 7-byte frames + checksum, 4-byte general response, command-2 motion bitmask, extended preset opcodes, speed fields 0x00..0x3F / 0xFF turbo, addressing 1..255 | `references/pelco-d-frames.md`, `scripts/pelco_conformance.py` |
| [`ptz-conformance-testing`](https://github.com/stritti/ptz-simulator/tree/main/.agents/skills/ptz-conformance-testing) | Validate any camera interface against the ptzsim reference: run it as the camera for your client, or smoke-test your own camera-side endpoint; conformance checklists incl. known deviations | `references/ptzsim-usage.md`, `references/conformance-checklist.md` |

## Install into your project

From a clone of this repository, the installer copies every skill into the skill
directories of the agents you choose:

```bash
./scripts/install-skills.sh /path/to/your-project              # all common agent skill directories
./scripts/install-skills.sh /path/to/your-project claude vibe   # selected agents only
./scripts/install-skills.sh --user ~                            # personal skills for all agents
```

Or copy by hand, e.g. for Claude Code:

```bash
mkdir -p /path/to/your-project/.claude/skills
cp -r .agents/skills/* /path/to/your-project/.claude/skills/
```

Or with the [skills CLI](https://github.com/vercel-labs/skills):
`npx skills add stritti/ptz-simulator --list`, then install with the agents you want
(e.g. `-a claude-code -a copilot --yes`) — see [On skills.sh](#on-skills-sh).

## On skills.sh

[skills.sh](https://skills.sh) is the directory of the open agent skills ecosystem. It
has no submission flow: a skill in a public GitHub repo is listed automatically once
people install it with the `skills` CLI. Because the skills live in `.agents/skills/`,
one of the CLI's standard discovery directories, this repository is installable as-is:

```bash
npx skills add stritti/ptz-simulator --list                   # list the skills in this repo
npx skills add stritti/ptz-simulator --skill visca-interface  # install one skill
npx skills add stritti/ptz-simulator --all -y                 # all skills into every agent
```

Installs with telemetry enabled (i.e. without `DISABLE_TELEMETRY=1` or
`DO_NOT_TRACK=1`) list the skills at
[skills.sh/stritti/ptz-simulator](https://skills.sh/stritti/ptz-simulator), and
`npx skills find ptz` makes them discoverable by keyword.

## Skill directories per agent

| Agent | Project skills | Personal skills |
|---|---|---|
| GitHub Copilot / VS Code | `.github/skills/`, `.claude/skills/`, `.agents/skills/` | `~/.copilot/skills/`, `~/.agents/skills/` |
| Claude Code | `.claude/skills/` | `~/.claude/skills/` |
| Mistral Vibe | `.vibe/skills/`, `.agents/skills/` (trusted dir) | `~/.vibe/skills/`, `~/.agents/skills/` |
| OpenAI Codex | `.agents/skills/` | `~/.agents/skills/` |
| Cursor | `.cursor/skills/` | `~/.cursor/skills/` |
| Gemini CLI | `.gemini/skills/` | `~/.gemini/skills/` |

## Using the bundled conformance scripts

The skills ship two standard-library-only smoke tests (Python 3.8+) that exit 0 only
when every wire-level check passes. Point them at your camera-side endpoint:

```bash
python3 visca_conformance.py --host 192.168.1.50 --transport sony           # VISCA over IP, UDP 52381
python3 visca_conformance.py --host 192.168.1.50 --transport tcp --port 5678
python3 pelco_conformance.py --port /dev/ttyUSB0 --address 1               # Pelco-D over serial
python3 onvif_conformance.py --host 192.168.1.50 --port 8080 --user admin --password secret --discovery
```

To validate a *client*, run the simulator and point the client at it instead — see
[testing ONVIF clients](/guide#testing-onvif-clients) and
[testing VISCA clients](/guide#testing-visca-clients) in the guide.

## Validation

[`tests/test_skills.py`](https://github.com/stritti/ptz-simulator/blob/main/tests/test_skills.py)
checks the `SKILL.md` frontmatter (name rules, description ≤ 1024 chars, ≤ 500 lines),
that relative links resolve, that the bundled scripts compile, and that
`scripts/install-skills.sh` copies the skills correctly — run it with `uv run pytest`.
