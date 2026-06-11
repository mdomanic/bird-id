"""Offline test path: identify birds in a local image or video clip.

Run the FULL pipeline (frame extraction -> Claude -> log/save/notify) against a
file on disk, without needing Arlo configured. Use this to confirm your API key
and bird-ID work before wiring up the camera.

    python identify_file.py path\\to\\bird.jpg
    python identify_file.py path\\to\\clip.mp4
"""
from __future__ import annotations

import sys
from pathlib import Path

from config import settings
from frames import extract_frames
from identifier import identify_birds
from pipeline import handle_frames


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print(__doc__)
        return 2

    path = Path(argv[0])
    if not path.exists():
        print(f"File not found: {path}")
        return 1

    print(f"Extracting frames from {path.name} ...")
    frames = extract_frames(path, count=settings.frames_per_clip)
    print(f"  got {len(frames)} frame(s). Asking Claude ({settings.bird_id_model}) ...")

    analysis = identify_birds(frames)
    print(f"\nSummary: {analysis.summary}")
    if not analysis.is_bird_present or not analysis.species:
        print("No birds identified.")
        return 0

    for sp in analysis.species:
        print(
            f"  - {sp.common_name} ({sp.scientific_name or 'n/a'}) "
            f"x{sp.count}  confidence={sp.confidence:.0%}\n"
            f"    field marks: {sp.field_marks}"
        )

    # Run the same persistence + notification path the live watcher uses.
    handle_frames(frames, analysis, source=f"file:{path.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
