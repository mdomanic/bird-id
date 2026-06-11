"""Read and update the .env file in place.

`update_env` preserves the file's existing comments, ordering, and blank lines —
it only rewrites the values of keys you change, and appends any brand-new keys at
the end. This keeps the friendly commented structure from .env.example intact
even after edits made through the web UI.
"""
from __future__ import annotations

import re
from pathlib import Path

from config import BASE_DIR

ENV_PATH = BASE_DIR / ".env"

# Characters that force quoting so the value round-trips through dotenv cleanly.
_NEEDS_QUOTING = re.compile(r"""[\s#"'=]""")


def _format_value(value: str) -> str:
    if value == "" or _NEEDS_QUOTING.search(value):
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return value


def _unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def read_env(path: Path = ENV_PATH) -> dict[str, str]:
    """Return the current KEY -> value pairs from the .env file."""
    result: dict[str, str] = {}
    if not path.exists():
        return result
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        result[key.strip()] = _unquote(value)
    return result


def update_env(changes: dict[str, str], path: Path = ENV_PATH) -> None:
    """Apply `changes` (KEY -> value) to the .env file, preserving structure."""
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    seen: set[str] = set()
    out: list[str] = []

    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in line:
            key = line.split("=", 1)[0].strip()
            if key in changes:
                out.append(f"{key}={_format_value(changes[key])}")
                seen.add(key)
                continue
        out.append(line)

    for key, value in changes.items():
        if key not in seen:
            out.append(f"{key}={_format_value(value)}")

    path.write_text("\n".join(out) + "\n", encoding="utf-8")
