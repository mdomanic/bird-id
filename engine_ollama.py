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
from io import BytesIO

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

    total = len(frames)
    per_frame: list[BirdAnalysis] = []
    last_error: Exception | None = None
    for i, frame in enumerate(frames, 1):
        try:
            result = _analyze_one(frame, prompt)
        except RuntimeError as exc:
            print(f"[ollama] frame {i}/{total} failed: {exc}")
            last_error = exc  # keep going; one bad frame shouldn't sink the event
            continue
        if result.species:
            top = max(result.species, key=lambda s: s.confidence)
            others = f" (+{len(result.species) - 1} more)" if len(result.species) > 1 else ""
            print(f"[ollama] frame {i}/{total}: {top.common_name} "
                  f"{top.confidence:.0%}{others}")
        else:
            print(f"[ollama] frame {i}/{total}: no bird — {result.summary[:80]}")
        per_frame.append(result)

    if not per_frame:
        # Every frame failed — surface the reason rather than a silent "no bird".
        raise last_error or RuntimeError("Ollama returned no usable result.")

    return _merge(per_frame)


def _downscale(frame: bytes) -> bytes:
    """Shrink a frame's longest edge to OLLAMA_IMAGE_MAX_EDGE before sending.

    A CPU vision model spends most of its time encoding pixels into image tokens,
    and that cost scales with area, so this is the biggest single speed lever.
    Returns the original bytes unchanged if downscaling is disabled, the image is
    already small enough, or Pillow can't read it.
    """
    max_edge = settings.ollama_image_max_edge
    if max_edge <= 0:
        return frame
    try:
        from PIL import Image
        img = Image.open(BytesIO(frame))
        img.load()
    except Exception:
        return frame  # never let a decode hiccup break identification
    w, h = img.size
    if max(w, h) <= max_edge:
        return frame
    scale = max_edge / max(w, h)
    img = img.convert("RGB").resize(
        (max(1, int(w * scale)), max(1, int(h * scale))), Image.LANCZOS
    )
    buf = BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return buf.getvalue()


def _analyze_one(frame: bytes, prompt: str) -> BirdAnalysis:
    image = base64.standard_b64encode(_downscale(frame)).decode("utf-8")
    options = {"temperature": 0}
    if settings.ollama_num_thread > 0:
        # Cap threads to the Ollama box's real core count; in an LXC it otherwise
        # oversubscribes host cores and generation slows by ~50x.
        options["num_thread"] = settings.ollama_num_thread
    payload = {
        "model": settings.ollama_model,
        "system": SYSTEM_PROMPT,
        "prompt": prompt,
        "images": [image],
        "format": "json",      # force syntactically valid JSON
        "stream": False,
        "keep_alive": settings.ollama_keep_alive,  # keep model resident between events
        "options": options,
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
    """Combine per-frame analyses with consensus voting.

    A VLM can name a different plausible species on each frame of one clip, so a
    naive "keep every species seen" merge turns one outlier frame into a false
    sighting. Instead we count how many frames each species appears in and, when
    multiple frames were analyzed, keep only those with real support: species
    seen in >=2 frames, or — if every frame disagreed — just the single most
    confident guess. Each kept species keeps its best confidence across frames.
    """
    best: dict[str, SpeciesSighting] = {}
    votes: dict[str, int] = {}
    for r in results:
        for key in {s.common_name.strip().lower() for s in r.species if s.common_name.strip()}:
            votes[key] = votes.get(key, 0) + 1
        for s in r.species:
            key = s.common_name.strip().lower()
            if key and (key not in best or s.confidence > best[key].confidence):
                best[key] = s

    if not best:
        return BirdAnalysis(
            is_bird_present=False, species=[], summary="No bird detected."
        )

    n = len(results)
    if n >= 2:
        max_votes = max(votes.values())
        if max_votes >= 2:
            keep = {k for k, v in votes.items() if v >= 2}
        else:
            # Every frame disagreed — trust only the single most confident call.
            keep = {max(best, key=lambda k: best[k].confidence)}
    else:
        keep = set(best)  # single frame: nothing to cross-check against

    species = sorted(
        (best[k] for k in keep), key=lambda s: (-votes[s.common_name.strip().lower()], -s.confidence)
    )
    if len(keep) < len(best):
        dropped = ", ".join(sorted(set(best) - keep))
        print(f"[ollama] consensus kept {len(keep)}/{len(best)} species across "
              f"{n} frames; dropped outliers: {dropped}")
    top = species[0]
    return BirdAnalysis(
        is_bird_present=True,
        species=species,
        summary=f"{top.common_name} ({top.confidence:.0%} confidence).",
    )


def _to_float(value, default: float = 0.0) -> float:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return default
    # Some models report confidence as a 0-100 percentage; normalize to 0-1.
    if f > 1.0:
        f = f / 100.0
    return max(0.0, min(1.0, f))


def _to_int(value, default: int = 1) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _parse(text: str) -> BirdAnalysis:
    """Build a BirdAnalysis from the model's JSON, tolerating schema drift.

    A small VLM won't always honor the exact schema — it may use 'name' instead
    of 'common_name', omit 'count'/'field_marks', give confidence as a string or
    a 0-100 percentage, or wrap the bird list under a different key. Rather than
    reject the whole response (and silently report "no bird"), we coerce what we
    can and log anything we can't parse at all.
    """
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        print(f"[ollama] non-JSON response: {text.strip()[:200]!r}")
        return BirdAnalysis(
            is_bird_present=False, species=[],
            summary="Ollama returned no parseable result.",
        )

    if not isinstance(data, dict):
        return BirdAnalysis(is_bird_present=False, species=[], summary="")

    raw = data.get("species")
    if not isinstance(raw, list):
        raw = data.get("birds") if isinstance(data.get("birds"), list) else []

    species: list[SpeciesSighting] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        name = str(item.get("common_name") or item.get("name") or "").strip()
        if not name:
            continue
        species.append(SpeciesSighting(
            common_name=name,
            scientific_name=(item.get("scientific_name") or None),
            confidence=_to_float(item.get("confidence")),
            count=_to_int(item.get("count")),
            field_marks=str(item.get("field_marks") or ""),
        ))

    summary = str(data.get("summary") or "").strip()
    is_present = bool(data.get("is_bird_present")) or bool(species)
    return BirdAnalysis(
        is_bird_present=is_present,
        species=species,
        summary=summary or ("Bird detected." if species else "No bird detected."),
    )
