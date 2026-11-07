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

From a clone of this repository, copy the skills into the skill directory of your agent
(see the table below) — the installer does all of them at once:

```bash
./scripts/install-skills.sh /path/to/your-project                 # all common agents
./scripts/install-skills.sh /path/to/your-project claude copilot   # selected agents only
./scripts/install-skills.sh --user ~                               # personal skills for all agents
```

Or copy one directory by hand, e.g. for Claude Code:

```bash
mkdir -p /path/to/your-project/.claude/skills
cp -r .agents/skills/* /path/to/your-project/.claude/skills/
```

Or with the [skills CLI](https://github.com/vercel-labs/skills):
`npx skills add stritti/ptz-simulator --list` (then pick agents/skills, e.g.
`-a claude-code -a copilot --yes`).

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
