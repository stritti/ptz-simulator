# SPDX-FileCopyrightText: 2026 Stephan Strittmatter
# SPDX-License-Identifier: MIT

"""The agent skills in .agents/skills/ must stay valid Agent Skills
(https://agentskills.io): SKILL.md frontmatter with a spec-conformant name and
description, working relative links, compilable bundled scripts, and an
install-skills.sh that copies them into the skill directories of the agents."""

import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SKILLS = ROOT / ".agents" / "skills"
INSTALLER = ROOT / "scripts" / "install-skills.sh"

NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
LINK_RE = re.compile(r"\[[^\]]*\]\(([^)]+)\)")


def skill_dirs():
    return sorted(d for d in SKILLS.iterdir() if d.is_dir() and (d / "SKILL.md").is_file())


def frontmatter(path: Path):
    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines and lines[0] == "---", "%s must start with '---' frontmatter" % path
    end = next(i for i in range(1, len(lines)) if lines[i] == "---")
    fields = {}
    for line in lines[1:end]:
        m = re.match(r"^([A-Za-z][\w-]*):\s*(.*)$", line)
        if m:
            value = m.group(2).strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            fields[m.group(1)] = value
    return fields, lines


def test_at_least_three_skills():
    assert len(skill_dirs()) >= 3


@pytest.mark.parametrize("skill", skill_dirs(), ids=lambda d: d.name)
def test_skill_md_frontmatter(skill):
    fields, lines = frontmatter(skill / "SKILL.md")
    name, description = fields.get("name", ""), fields.get("description", "")
    assert name, "name is required"
    assert NAME_RE.match(name), "name must be lowercase-hyphen: %r" % name
    assert len(name) <= 64
    assert name == skill.name, "name must match the directory: %r != %r" % (name, skill.name)
    assert description, "description is required"
    assert len(description) <= 1024
    assert len(lines) <= 500, "keep SKILL.md under 500 lines, details go to references/"


@pytest.mark.parametrize("skill", skill_dirs(), ids=lambda d: d.name)
def test_skill_relative_links_exist(skill):
    text = (skill / "SKILL.md").read_text(encoding="utf-8")
    for target in LINK_RE.findall(text):
        if re.match(r"^[a-z]+:", target) or target.startswith("#"):
            continue
        assert (skill / target).exists(), "%s links to missing %s" % (skill.name, target)


@pytest.mark.parametrize("skill", skill_dirs(), ids=lambda d: d.name)
def test_skill_scripts_compile(skill):
    for script in sorted(skill.rglob("*.py")):
        compile(script.read_text(encoding="utf-8"), str(script), "exec")


def test_install_skills_sh_syntax_and_help():
    subprocess.run(["sh", "-n", str(INSTALLER)], check=True)
    result = subprocess.run(["sh", str(INSTALLER), "--help"], capture_output=True, text=True)
    assert result.returncode == 0
    assert "install-skills.sh" in result.stdout


def test_install_skills_copies_into_project(tmp_path):
    result = subprocess.run(
        ["sh", str(INSTALLER), str(tmp_path), "claude", "vibe"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    for tool_dir in (".claude/skills", ".vibe/skills"):
        for skill in skill_dirs():
            assert (tmp_path / tool_dir / skill.name / "SKILL.md").is_file()
