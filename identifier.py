"""Bird identification: shared result schema + engine dispatcher.

Engines (select with BIRD_ID_ENGINE in .env):
  - "local"  : free, on-device TFLite classifier (engine_local). Default.
  - "claude" : Claude vision API (engine_claude). Costs API credits, but adds
               reasoning ("that's a squirrel"), field marks, and open-ended species.

The heavy per-engine dependencies (tflite / anthropic) are imported lazily inside
the dispatcher so you only need the libraries for the engine you actually use.
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from config import settings


class SpeciesSighting(BaseModel):
    common_name: str = Field(description="Common name, e.g. 'American Robin'.")
    scientific_name: Optional[str] = Field(
        default=None, description="Binomial name if known, e.g. 'Turdus migratorius'."
    )
    confidence: float = Field(description="Confidence from 0.0 to 1.0.")
    count: int = Field(description="How many individuals of this species are visible.")
    field_marks: str = Field(
        description="Visual features used to identify it (or engine note)."
    )


class BirdAnalysis(BaseModel):
    is_bird_present: bool = Field(description="True if at least one bird is visible.")
    species: list[SpeciesSighting] = Field(
        description="One entry per distinct species seen. Empty if no birds."
    )
    summary: str = Field(description="One short sentence describing the scene.")


def identify_birds(frames: list[bytes]) -> BirdAnalysis:
    """Identify bird species across a set of JPEG frames using the configured engine."""
    if not frames:
        return BirdAnalysis(is_bird_present=False, species=[], summary="No frames to analyze.")

    engine = (settings.bird_id_engine or "local").lower()
    if engine == "claude":
        from engine_claude import analyze
    elif engine == "ollama":
        from engine_ollama import analyze
    elif engine in ("local", "tflite"):
        from engine_local import analyze
    else:
        raise RuntimeError(
            f"Unknown BIRD_ID_ENGINE '{engine}'. Use 'local', 'ollama', or 'claude'."
        )
    return analyze(frames)
