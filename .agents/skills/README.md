<!--
SPDX-FileCopyrightText: 2026 Stephan Strittmatter
SPDX-License-Identifier: MIT
-->

# ptzsim agent skills

[Agent Skills](https://agentskills.io) (a directory with a `SKILL.md` plus optional
`references/`, `scripts/`, `assets/`) that help any project implement a
**reference-conformant PTZ camera interface** — wire-exact VISCA, ONVIF or Pelco-D — and validate
it against the [ptzsim](https://github.com/stritti/ptz-simulator) reference simulator.

| Skill | Purpose |
|---|---|
| `ptz-reference-interface` | Entry point: choose the protocol, implement, validate, document |
| `visca-interface` | VISCA over RS-232/422 and VISCA over IP (UDP 52381): framing, commands, inquiries, replies, sockets, ranges + `scripts/visca_conformance.py` |
| `onvif-ptz-interface` | ONVIF Profile S/T PTZ service: SOAP services, spaces, faults, WS-Discovery, auth + `scripts/onvif_conformance.py` |
| `pelco-d-interface` | Pelco-D serial (RS-485): 7-byte frames + checksum, general response, motion bitmask, preset opcodes, speeds + `scripts/pelco_conformance.py` |
| `ptz-conformance-testing` | Test any camera interface against ptzsim; conformance checklists |

## Install into your project

Install the skills with the [skills CLI](https://skills.sh) straight from this
repository — no clone needed, this directory is one of the CLI's standard discovery
directories:

```bash
npx skills add stritti/ptz-simulator --list                   # list the skills in this repo
npx skills add stritti/ptz-simulator --skill visca-interface  # install one skill
npx skills add stritti/ptz-simulator --all -y                 # all skills into every agent
```

Use `-g` to install into your personal skill directories (e.g. `~/.claude/skills/`)
instead of the project, when the project should not commit the skill files:
`npx skills add stritti/ptz-simulator --skill visca-interface -a claude-code -g -y`.
`npx` needs Node on the `PATH` of the shell that runs it: when Node comes from nvm
(or fnm, asdf, …) and an agent runs the command in a non-interactive shell such as
`bash -lc`, the shell profile that loads nvm is not read and `npx` is not found; run it
in your interactive shell, or load nvm first (`. ~/.nvm/nvm.sh && npx skills add …`).

Choose the agents with `-a` (e.g. `-a claude-code -a copilot --yes`). The skills are
listed at [skills.sh/stritti/ptz-simulator](https://skills.sh/stritti/ptz-simulator).

In this repository the skills live in `.agents/skills/`, which GitHub Copilot (VS Code /
CLI / cloud), OpenAI Codex, Mistral Vibe and other agents read directly.

## Skill directories per agent

| Agent | Project skills | Personal skills |
|---|---|---|
| GitHub Copilot / VS Code | `.github/skills/`, `.claude/skills/`, `.agents/skills/` | `~/.copilot/skills/`, `~/.agents/skills/` |
| Claude Code | `.claude/skills/` | `~/.claude/skills/` |
| Mistral Vibe | `.vibe/skills/`, `.agents/skills/` (trusted dir) | `~/.vibe/skills/`, `~/.agents/skills/` |
| OpenAI Codex | `.agents/skills/` | `~/.agents/skills/` |
| Cursor | `.cursor/skills/` | `~/.cursor/skills/` |
| Gemini CLI | `.gemini/skills/` | `~/.gemini/skills/` |

SKILL.md format: YAML frontmatter with `name` (lowercase-hyphen, matches the directory,
≤ 64 chars) and `description` (≤ 1024 chars, says what the skill does and when to use
it), then Markdown instructions (≤ 500 lines; put details into `references/`). The
bundled `scripts/` are Python 3.8+ standard-library only.
`tests/test_skills.py` in the repository validates all of this.
