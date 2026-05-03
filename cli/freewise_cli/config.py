"""CLI config: env vars + on-disk TOML at $XDG_CONFIG_HOME/freewise/config.toml.

Resolution order for url and token (highest precedence first):

1. Explicit ``--url`` / ``--token`` flags (handled by main.py).
2. ``FREEWISE_URL`` / ``FREEWISE_TOKEN`` env vars.
3. ``[default]`` section of ~/.config/freewise/config.toml.
4. Hard-coded defaults (url=http://localhost:8063, token=None).
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib  # type: ignore[no-redef]


DEFAULT_URL = "http://localhost:8063"


@dataclass
class Config:
    url: str
    token: str | None
    source: str  # short label noting where the values came from (for `auth status`)


def _config_path() -> Path:
    base = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config")))
    return base / "freewise" / "config.toml"


def load() -> Config:
    """Resolve config from env first, then disk, then defaults."""
    env_url = os.environ.get("FREEWISE_URL")
    env_token = os.environ.get("FREEWISE_TOKEN")
    if env_url or env_token:
        return Config(
            url=(env_url or DEFAULT_URL).rstrip("/"),
            token=env_token,
            source="env",
        )

    path = _config_path()
    if path.exists():
        try:
            data = tomllib.loads(path.read_text(encoding="utf-8"))
        except (tomllib.TOMLDecodeError, OSError):
            data = {}
        section = data.get("default", {})
        return Config(
            url=str(section.get("url") or DEFAULT_URL).rstrip("/"),
            token=section.get("token"),
            source=str(path),
        )

    return Config(url=DEFAULT_URL, token=None, source="defaults")


def save(url: str, token: str) -> Path:
    """Persist url + token to ~/.config/freewise/config.toml. Returns the path."""
    path = _config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    # Hand-rolled TOML to avoid an extra runtime dep — this format is dead simple.
    body = f'[default]\nurl = "{url.rstrip("/")}"\ntoken = "{token}"\n'
    path.write_text(body, encoding="utf-8")
    # Tighten permissions so a token in $HOME isn't world-readable.
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return path
