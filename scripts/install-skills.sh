#!/bin/sh
# SPDX-FileCopyrightText: 2026 Stephan Strittmatter
# SPDX-License-Identifier: MIT

# Install the ptzsim agent skills (.agents/skills/) into a project or into the
# personal skill directories of your AI coding agents (Claude Code, GitHub
# Copilot, Mistral Vibe, Cursor, Codex, ...). Each agent reads SKILL.md files
# from its own skill directory; this script copies every skill there.
#
# Usage:
#   install-skills.sh [--user] TARGET [TOOL ...]
#
#   TARGET   project directory to install into (with --user: the home directory,
#            default $HOME when --user is given without a target)
#   TOOL     one of: copilot claude agents cursor vibe codex gemini windsurf
#            opencode cline roo  --  default: all
#
# Examples:
#   ./scripts/install-skills.sh /path/to/my-project
#   ./scripts/install-skills.sh /path/to/my-project claude copilot
#   ./scripts/install-skills.sh --user          # personal skills for all agents
#   ./scripts/install-skills.sh --user ~ vibe

set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
SKILLS_DIR=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)/.agents/skills

ALL_TOOLS="copilot claude agents cursor vibe codex gemini windsurf opencode cline roo"

usage() {
    sed -n '2,25p' "$0" | sed 's/^# \{0,1\}//'
}

project_dir_for() {
    case "$1" in
        copilot)  echo .github/skills ;;
        claude)   echo .claude/skills ;;
        agents)   echo .agents/skills ;;
        cursor)   echo .cursor/skills ;;
        vibe)     echo .vibe/skills ;;
        codex)    echo .codex/skills ;;
        gemini)   echo .gemini/skills ;;
        windsurf) echo .windsurf/skills ;;
        opencode) echo .opencode/skills ;;
        cline)    echo .cline/skills ;;
        roo)      echo .roo/skills ;;
        *)        echo "unknown tool: $1" >&2; exit 2 ;;
    esac
}

user_dir_for() {
    case "$1" in
        copilot)  echo .copilot/skills ;;
        *)        project_dir_for "$1" ;;
    esac
}

USER_MODE=0
if [ "${1:-}" = "--user" ]; then
    USER_MODE=1
    shift
fi

if [ "${1:-}" = "--help" ] || [ "${1:-}" = "-h" ]; then
    usage
    exit 0
fi

if [ "$USER_MODE" = 1 ]; then
    TARGET=${1:-$HOME}
    [ "$#" -gt 0 ] && shift
else
    if [ $# -lt 1 ]; then
        echo "error: TARGET project directory required (or --user for personal skills)" >&2
        usage >&2
        exit 2
    fi
    TARGET=$1
    shift
fi

TOOLS=${*:-}
if [ -z "$TOOLS" ]; then
    TOOLS=$ALL_TOOLS
fi

if [ ! -d "$SKILLS_DIR" ]; then
    echo "error: skills not found at $SKILLS_DIR" >&2
    exit 1
fi
if [ ! -d "$TARGET" ]; then
    echo "error: target directory does not exist: $TARGET" >&2
    exit 2
fi

SKILLS=$(CDPATH= cd -- "$SKILLS_DIR" && ls -d */ 2>/dev/null | sed 's:/$::')
if [ -z "$SKILLS" ]; then
    echo "error: no skills (directories with SKILL.md) in $SKILLS_DIR" >&2
    exit 1
fi

for tool in $TOOLS; do
    if [ "$USER_MODE" = 1 ]; then
        dir=$(user_dir_for "$tool")
    else
        dir=$(project_dir_for "$tool")
    fi
    dest="$TARGET/$dir"
    mkdir -p "$dest"
    for skill in $SKILLS; do
        if [ -f "$SKILLS_DIR/$skill/SKILL.md" ]; then
            rm -rf "$dest/$skill"
            cp -R "$SKILLS_DIR/$skill" "$dest/$skill"
        fi
    done
    printf 'installed %s -> %s (%s)\n' "$(echo $SKILLS | tr '\n' ' ')" "$dest" "$tool"
done
