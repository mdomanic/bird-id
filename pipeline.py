"""Shared post-identification handling: pick a frame, persist, notify.

Both the live Arlo watcher and the offline test CLI call `process_source`, so
the behaviour (logging, image saving, new-species notifications) is identical no
matter where the frames came from.
"""
from __future__ import annotations

from pathlib import Path

from config import settings
from frames import extract_frames
from identifier import BirdAnalysis, identify_birds
from notifier import notify
from storage import known_species, record_sighting, save_frame


def handle_frames(frames: list[bytes], analysis: BirdAnalysis, source: str) -> list[str]:
    """Persist and notify for an already-analyzed set of frames.

    Returns the list of species names that were logged (above the confidence
    threshold). Shared by `identify_file.py` and the live watcher.
    """
    if not analysis.is_bird_present or not analysis.species:
        return []

    # Save the first frame as a representative image for this event.
    image_path: Path | None = save_frame(frames[0], event_id=source) if frames else None

    seen_before = known_species()
    logged = record_sighting(
        analysis,
        source=source,
        image_path=image_path,
        min_confidence=settings.min_confidence,
    )
    if not logged:
        return []

    new_species = [name for name in logged if name not in seen_before]

    should_notify = (
        settings.notify_mode == "all"
        or (settings.notify_mode == "new" and new_species)
    )
    if should_notify:
        headline = ", ".join(new_species or logged)
        prefix = "New bird: " if new_species else "Bird seen: "
        notify(
            title=f"{prefix}{headline}",
            message=analysis.summary,
            image_path=image_path,
        )
    return logged


def process_source(path: str | Path, source: str) -> list[str]:
    """Full pipeline for a clip/image path: extract -> identify -> handle."""
    frames = extract_frames(path, count=settings.frames_per_clip)
    if not frames:
        print(f"[pipeline] no frames extracted from {path}")
        return []
    analysis = identify_birds(frames)
    print(f"[pipeline] {source}: {analysis.summary}")
    return handle_frames(frames, analysis, source=source)
