"""Record one use of a skill in HERMES_HOME's skills/.usage.json. Runs under the Hermes interpreter.

Usage: usage.py <skill folder> <session id>
The usage record is keyed by the skill's frontmatter name, which can differ from its folder name.
"""

import sys
from pathlib import Path

from tools.skill_usage import bump_use, bump_view, read_skill_name

folder, session = Path(sys.argv[1]), sys.argv[2]
name = read_skill_name(folder / "SKILL.md", folder.name)
bump_view(name)
bump_use(name, session_id=session or None)
