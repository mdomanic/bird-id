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
from identifier import BirdAnalysis, SpeciesSighting

SYSTEM_PROMPT = """\
You are an expert ornithologist identifying birds from a single security-camera
frame. Be honest about confidence: low for blurry/distant/partial birds, high
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
    """Identify birds across frames.

    Ollama's /api/generate takes one image per call for these vision models
    (multiple images in one request are rejected with HTTP 400), so we send each
    frame separately and merge — keeping the highest-confidence sighting per
    species, the same strategy the local engine uses.
    """
    location = (
        f"Approximate location: {settings.location_hint}. "
        if settings.location_hint
        else ""
    )
    prompt = (
        f"{location}Here is one frame from a motion event. "
        "Identify any birds present and respond with the JSON object."
    )

    per_frame: list[BirdAnalysis] = []
    last_error: Exception | None = None
    for frame in frames:
        try:
            per_frame.append(_analyze_one(frame, prompt))
        except RuntimeError as exc:
            last_error = exc  # keep going; one bad frame shouldn't sink the event

    if not per_frame:
        # Every frame failed — surface the reason rather than a silent "no bird".
        raise last_error or RuntimeError("Ollama returned no usable result.")

    return _merge(per_frame)


def _analyze_one(frame: bytes, prompt: str) -> BirdAnalysis:
    image = base64.standard_b64encode(frame).decode("utf-8")
    payload = {
        "model": settings.ollama_model,
        "system": SYSTEM_PROMPT,
        "prompt": prompt,
        "images": [image],
        "format": "json",      # force syntactically valid JSON
        "stream": False,
        "keep_alive": settings.ollama_keep_alive,  # keep model resident between events
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
    except TimeoutError as exc:
        # A socket timeout is TimeoutError, NOT a URLError — catch it explicitly
        # and raise RuntimeError so the per-frame loop continues. The model stays
        # loaded after a cold-load timeout, so a later frame often runs warm.
        raise RuntimeError(
            f"Ollama at {url} timed out after {settings.ollama_timeout}s "
            f"(model '{settings.ollama_model}' may still be cold-loading). "
            "Raise OLLAMA_TIMEOUT, lower FRAMES_PER_CLIP, or pin CPU/NUMA."
        ) from exc
    except urllib.error.HTTPError as exc:
        # Ollama explains *why* it rejected the request in the response body
        # (e.g. {"error":"model '...' not found, try pulling it first"}).
        try:
            detail = exc.read().decode("utf-8", "replace").strip()
        except Exception:
            detail = ""
        raise RuntimeError(
            f"Ollama at {url} returned HTTP {exc.code}: {detail or exc.reason}. "
            f"Check that model '{settings.ollama_model}' is pulled "
            f"(ollama list) and that Ollama is new enough to run it."
        ) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(
            f"Could not reach Ollama at {url}: {exc}. Is the server up and the "
            "model pulled?"
        ) from exc

    return _parse(body.get("response", ""))


def _merge(results: list[BirdAnalysis]) -> BirdAnalysis:
    """Combine per-frame analyses: best confidence per species across frames."""
    best: dict[str, SpeciesSighting] = {}
    for r in results:
        for s in r.species:
            key = s.common_name.strip().lower()
            if key not in best or s.confidence > best[key].confidence:
                best[key] = s

    if not best:
        return BirdAnalysis(
            is_bird_present=False, species=[], summary="No bird detected."
        )

    species = sorted(best.values(), key=lambda s: -s.confidence)
    top = species[0]
    return BirdAnalysis(
        is_bird_present=True,
        species=species,
        summary=f"{top.common_name} ({top.confidence:.0%} confidence).",
    )


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
