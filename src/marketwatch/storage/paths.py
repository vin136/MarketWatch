from __future__ import annotations

import os
from pathlib import Path


ENV_HOME = "MARKETWATCH_HOME"
CURRENT_FILE_NAME = "current"


def get_base_dir() -> Path:
    env = os.environ.get(ENV_HOME)
    if env:
        return Path(env).expanduser()
    return Path.home() / ".marketwatch"


def get_current_portfolio_dir() -> Path | None:
    base_dir = get_base_dir()
    current_path = base_dir / CURRENT_FILE_NAME
    if not current_path.exists():
        return None
    text = current_path.read_text(encoding="utf-8").strip()
    if not text:
        return None
    return Path(text)


def set_current_portfolio_dir(path: Path) -> None:
    base_dir = get_base_dir()
    base_dir.mkdir(parents=True, exist_ok=True)
    current_path = base_dir / CURRENT_FILE_NAME
    current_path.write_text(str(path), encoding="utf-8")


def get_portfolio_dir(name: str | None, directory: Path | None) -> Path:
    if directory is not None:
        return directory
    if name is not None:
        return get_base_dir() / name
    current = get_current_portfolio_dir()
    if current is None:
        msg = (
            "No current portfolio is set. Run 'mw init' first or "
            "pass --portfolio/--dir explicitly."
        )
        raise RuntimeError(msg)
    return current


