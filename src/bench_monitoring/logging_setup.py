from __future__ import annotations

import logging.config
from pathlib import Path

import yaml

from .config import MODULE_ROOT, PROJECT_ROOT


def setup_logging() -> None:
    config_path = MODULE_ROOT / "configs" / "logging.yaml"
    Path(PROJECT_ROOT / "logs").mkdir(parents=True, exist_ok=True)
    with config_path.open("r", encoding="utf-8") as file:
        config = yaml.safe_load(file)
    logging.config.dictConfig(config)