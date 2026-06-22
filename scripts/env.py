"""
Load .env from the project root into os.environ.

Simple key=value parser — no external dependencies. Skips blank lines and
comments. Does not override variables already set in the environment, so
a real exported variable always wins over .env.
"""
from __future__ import annotations

import os
from pathlib import Path

# Project root is the directory containing this file's parent (scripts/)
PROJECT_ROOT = Path(__file__).resolve().parent.parent


def load_dotenv() -> None:
    env_path = PROJECT_ROOT / ".env"
    if not env_path.exists():
        return
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value
