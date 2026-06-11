"""Ollama engine: local vision-LLM bird ID, run on your own server (free).

Used when BIRD_ID_ENGINE=ollama. Talks to an Ollama server (OLLAMA_URL) running a
vision model (OLLAMA_MODEL) — e.g. a beefy CPU box on your network. Gives
Claude-style reasoning and field marks with no per-image cost.

Uses only the standard library (urllib) so there's no extra dependency.
"""
from __future__ import annotations

import base64
import json
import urllib.error
import urllib.request

from config import settings
from identifier import BirdAnalysis

SYSTEM_PROMPT = """\
You are an expert ornithologist identifying birds from security-camera frames.
The frames are from one short motion event, so the same bird may appear several
times. Be honest about confidence: low for blurry/distant/partial birds, high
only for clear views. Only report actual birds — if the motion was a person,
pet, squirrel, vehicle, leaves, or nothing identifiable, report no birds. Do not
invent a species; if you see a bird but can't tell what it is, use
"Unidentified bird" with low confidence.

Return ONLY a JSON object with exactly these keys:
{
  "is_bird_present": boolean,
  "species": [
    {
      "common_name": string,
      "scientific_name": string or null,
      "confidence": number between 0 and 1,
      "count": integer,
      "field_marks": string
    }
  ],
  "summary": string  // one short sentence
}
If no bird is present, set is_bird_present to false and species to []."""


def analyze(frames: list[bytes]) -> BirdAnalysis:
    images = [base64.standard_b64encode(f).decode("utf-8") for f in frames]
    location = (
        f"Approximate location: {settings.location_hint}. "
        if settings.location_hint
        else ""
    )

    payload = {
        "model": settings.ollama_model,
        "system": SYSTEM_PROMPT,
        "prompt": (
            f"{location}Here are {len(frames)} frame(s) from one motion event. "
            "Identify any birds present and respond with the JSON object."
        ),
        "images": images,
        "format": "json",      # force syntactically valid JSON
        "stream": False,
        "options": {"temperature": 0},
    }

    url = settings.ollama_url.rstrip("/") + "/api/generate"
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=settings.ollama_timeout) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        raise RuntimeError(
            f"Could not reach Ollama at {url}: {exc}. Is the server up and the "
            "model pulled?"
        ) from exc

    return _parse(body.get("response", ""))


def _parse(text: str) -> BirdAnalysis:
    try:
        return BirdAnalysis.model_validate_json(text)
    except Exception:
        # Model didn't return clean schema-matching JSON — fail safe.
        snippet = text.strip()[:160]
        return BirdAnalysis(
            is_bird_present=False,
            species=[],
            summary=snippet or "Ollama returned no parseable result.",
        )
