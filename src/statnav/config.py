"""Config loading: YAML files under configs/, with ${VAR:default} expansion from the environment."""

from __future__ import annotations

import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT / "configs"

_ENV_PATTERN = re.compile(r"\$\{([A-Z0-9_]+)(?::([^}]*))?\}")


def _expand(value: Any) -> Any:
    if isinstance(value, str):
        full = _ENV_PATTERN.fullmatch(value)
        if full:
            # A value that is only a placeholder keeps the YAML type of its default (e.g. int port)
            raw = os.environ.get(full.group(1), full.group(2) or "")
            return yaml.safe_load(raw) if raw else raw
        return _ENV_PATTERN.sub(lambda m: os.environ.get(m.group(1), m.group(2) or ""), value)
    if isinstance(value, dict):
        return {k: _expand(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand(v) for v in value]
    return value


def load_yaml(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as f:
        return _expand(yaml.safe_load(f) or {})


@lru_cache(maxsize=1)
def base_config() -> dict[str, Any]:
    load_dotenv(ROOT / ".env")
    return load_yaml(CONFIG_DIR / "base.yaml")


def pdf_path() -> Path:
    return ROOT / base_config()["source"]["pdf_path"]


def db_dsn() -> str:
    db = base_config()["db"]
    return (
        f"host={db['host']} port={db['port']} user={db['user']} "
        f"password={db['password']} dbname={db['dbname']}"
    )
