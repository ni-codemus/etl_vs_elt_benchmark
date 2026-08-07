from __future__ import annotations

import os
import subprocess
from pathlib import Path

from dotenv import load_dotenv


project_root = Path(__file__).resolve().parents[2]

env_file = Path(project_root / "configs" / ".env")
if env_file.exists():
    load_dotenv(env_file)
else:
    raise FileNotFoundError("Le fichier de config est .env est introuvable.")


PROJECT_ROOT = project_root
MODULE_ROOT = PROJECT_ROOT

os.environ.setdefault("PROJECT_ROOT", str(PROJECT_ROOT))