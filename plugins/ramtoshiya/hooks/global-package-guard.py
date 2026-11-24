import os
from pathlib import Path

binary = Path(__file__).resolve().parent / "ramtoshiya-hooks"
os.execv(binary, [str(binary), "guard"])
