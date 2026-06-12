"""Entry point for the live bird monitor.

Logs into Arlo, watches every (or selected) camera for motion, downloads each
recorded clip, identifies any birds with Claude, and logs / saves / notifies.

    python main.py

Stop with Ctrl+C. View results with `python dashboard.py`.
"""
from __future__ import annotations

from pathlib import Path

from arlo_client import ArloWatcher
from config import settings
from pipeline import process_source
from storage import init_db


def _on_clip(clip_path: Path, source: str) -> None:
    logged = process_source(clip_path, source=source)
    if logged:
        print(f"[main] logged from {source}: {', '.join(logged)}")
    else:
        print(f"[main] no confident birds from {source}")


def main() -> int:
    engine = (settings.bird_id_engine or "local").lower()

    # Fail fast on the things most likely to be misconfigured. The Anthropic key
    # is only needed for the "claude" engine — local/ollama run without it.
    if engine == "claude" and not settings.anthropic_api_key:
        print("ERROR: BIRD_ID_ENGINE=claude but ANTHROPIC_API_KEY is not set. "
              "Set the key, or switch to the free 'local'/'ollama' engine.")
        return 1
    if not (settings.arlo_username and settings.arlo_password):
        print("ERROR: Arlo credentials are not set. Edit .env (ARLO_USERNAME / "
              "ARLO_PASSWORD and the ARLO_TFA_* fields).")
        return 1

    settings.ensure_dirs()
    init_db()

    if engine == "claude":
        engine_desc = f"claude ({settings.bird_id_model})"
    elif engine == "ollama":
        engine_desc = f"ollama ({settings.ollama_model} @ {settings.ollama_url})"
    else:
        engine_desc = "local (on-device classifier)"

    print(f"Bird ID monitor starting. Engine: {engine_desc}. "
          f"Notify mode: {settings.notify_mode}.")
    watcher = ArloWatcher(on_clip=_on_clip)
    watcher.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
