"""Bird identification via Claude's vision API.

Given one or more JPEG frames, ask Claude (an expert-birder persona) which bird
species are present, with a confidence score and the field marks it used. The
response is constrained to a Pydantic schema via structured outputs, so callers
get validated objects instead of having to parse free text.
"""
from __future__ import annotations

import base64
from typing import Optional

import anthropic
from pydantic import BaseModel, Field

from config import settings

# --- Output schema -----------------------------------------------------------


class SpeciesSighting(BaseModel):
    common_name: str = Field(description="Common name, e.g. 'American Robin'.")
    scientific_name: Optional[str] = Field(
        default=None, description="Binomial name if known, e.g. 'Turdus migratorius'."
    )
    confidence: float = Field(description="Confidence from 0.0 to 1.0.")
    count: int = Field(description="How many individuals of this species are visible.")
    field_marks: str = Field(
        description="The visual features used to identify it (color, size, beak, markings)."
    )


class BirdAnalysis(BaseModel):
    is_bird_present: bool = Field(description="True if at least one bird is visible.")
    species: list[SpeciesSighting] = Field(
        description="One entry per distinct species seen. Empty if no birds."
    )
    summary: str = Field(description="One short sentence describing the scene.")


# --- Prompt ------------------------------------------------------------------
# Kept static (no per-request data) so it can be prompt-cached. Anything that
# varies per request (location, timestamp) goes in the user turn instead, which
# preserves the cached prefix.
SYSTEM_PROMPT = """\
You are an expert ornithologist identifying birds from security-camera frames.

You will receive one or more frames captured from the same short motion event,
so the same bird may appear in several frames from slightly different angles.
Treat the frames together as evidence about a single scene.

Identify every distinct bird species visible. For each species:
- Give the common name and, if you are reasonably sure, the scientific name.
- Estimate how many individuals of that species are visible.
- Report your confidence from 0.0 to 1.0. Be honest: use lower values when the
  bird is blurry, distant, partially hidden, or could be confused with a
  similar species. Use high values only for clear, unambiguous views.
- Describe the field marks you used (size, shape, color, beak, markings, posture).

Rules:
- Only report actual birds. If the motion was a person, pet, vehicle, blowing
  leaves, an insect, or nothing identifiable, set is_bird_present to false and
  return an empty species list.
- Do not invent a species to be helpful. If you can see a bird but genuinely
  cannot tell what it is, report it as common_name "Unidentified bird" with a
  low confidence and describe what you can see.
- If a location hint is provided, use it to weight toward locally plausible
  species, but never let it override clear visual evidence.\
"""


_client: anthropic.Anthropic | None = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        if not settings.anthropic_api_key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY is not set. Add it to your .env file."
            )
        _client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    return _client


def _image_block(jpeg_bytes: bytes) -> dict:
    return {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": "image/jpeg",
            "data": base64.standard_b64encode(jpeg_bytes).decode("utf-8"),
        },
    }


def identify_birds(frames: list[bytes]) -> BirdAnalysis:
    """Identify bird species across a set of JPEG frames."""
    if not frames:
        return BirdAnalysis(is_bird_present=False, species=[], summary="No frames to analyze.")

    client = _get_client()

    location_line = (
        f"Approximate location: {settings.location_hint}.\n"
        if settings.location_hint
        else ""
    )
    user_content: list[dict] = [
        {
            "type": "text",
            "text": (
                f"{location_line}"
                f"Here are {len(frames)} frame(s) from one motion event. "
                "Identify any birds present."
            ),
        }
    ]
    user_content.extend(_image_block(f) for f in frames)

    # `messages.parse` validates the response against BirdAnalysis and returns a
    # typed object (it derives output_config.format from output_format for us).
    # Adaptive thinking lets the model reason about tricky IDs; cache_control on
    # the (static) system prompt enables prompt caching.
    response = client.messages.parse(
        model=settings.bird_id_model,
        max_tokens=2000,
        thinking={"type": "adaptive"},
        system=[
            {
                "type": "text",
                "text": SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[{"role": "user", "content": user_content}],
        output_format=BirdAnalysis,
    )

    result = response.parsed_output
    if result is None:
        # Refusal or schema miss — fail safe rather than crash the watcher.
        return BirdAnalysis(
            is_bird_present=False,
            species=[],
            summary="Model did not return a parseable result.",
        )
    return result
