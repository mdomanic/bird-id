"""Claude vision engine: identify birds via the Anthropic API.

Used when BIRD_ID_ENGINE=claude. Costs API credits, but gives reasoning, field
marks, open-ended species, and graceful "that's not a bird" handling.
"""
from __future__ import annotations

import base64

import anthropic

from config import settings
from identifier import BirdAnalysis

# Static (cacheable) instructions. Per-request data (location) goes in the user
# turn so it doesn't break prompt caching.
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
            raise RuntimeError("ANTHROPIC_API_KEY is not set. Add it to your .env file.")
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


def analyze(frames: list[bytes]) -> BirdAnalysis:
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
                f"{location_line}Here are {len(frames)} frame(s) from one motion "
                "event. Identify any birds present."
            ),
        }
    ]
    user_content.extend(_image_block(f) for f in frames)

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
        return BirdAnalysis(
            is_bird_present=False,
            species=[],
            summary="Model did not return a parseable result.",
        )
    return result
