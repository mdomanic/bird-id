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
    # Fail fast on the two things most likely to be misconfigured.
    if not settings.anthropic_api_key:
        print("ERROR: ANTHROPIC_API_KEY is not set. Copy .env.example to .env "
              "and fill it in.")
        return 1
    if not (settings.arlo_username and settings.arlo_password):
        print("ERROR: Arlo credentials are not set. Edit .env (ARLO_USERNAME / "
              "ARLO_PASSWORD and the ARLO_TFA_* fields).")
        return 1

    settings.ensure_dirs()
    init_db()

    print(f"Bird ID monitor starting. Model: {settings.bird_id_model}. "
          f"Notify mode: {settings.notify_mode}.")
    watcher = ArloWatcher(on_clip=_on_clip)
    watcher.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
