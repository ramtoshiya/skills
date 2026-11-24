import os
from pathlib import Path

binary = Path(__file__).resolve().parent.parent.parent / "ramtoshiya" / "hooks" / "ramtoshiya-hooks"
os.execv(binary, [str(binary), "commit-trailer"])
