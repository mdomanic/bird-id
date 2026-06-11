"""Local engine: free, on-device bird classification with a TFLite model.

Uses a MobileNet classifier trained on the iNaturalist bird dataset (~960 species
plus a "background" class for non-birds). Runs on CPU in milliseconds with no API
cost and no data leaving your machine.

Download the model + labels once with `scripts/get_model.sh` (setup.sh does this
for you). Tradeoffs vs. the Claude engine: species-only output (no reasoning or
field-mark explanations) and a fixed species list, but $0 to run.
"""
from __future__ import annotations

from functools import lru_cache
from io import BytesIO
from pathlib import Path

import numpy as np
from PIL import Image

from config import settings
from identifier import BirdAnalysis, SpeciesSighting

INPUT_SIZE = 224


@lru_cache(maxsize=1)
def _load():
    """Load the interpreter and labels once (cached for the process lifetime)."""
    try:
        from tflite_runtime.interpreter import Interpreter
    except ImportError:  # fall back to full TensorFlow if tflite-runtime is absent
        try:
            from tensorflow.lite import Interpreter  # type: ignore
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "The local engine needs a TFLite runtime. Install it with "
                "`pip install tflite-runtime` (Linux) or `pip install tensorflow`."
            ) from exc

    model_path = Path(settings.bird_model_path)
    labels_path = Path(settings.bird_labels_path)
    if not model_path.exists() or not labels_path.exists():
        raise RuntimeError(
            f"Bird model/labels not found ({model_path}). "
            "Download them with `bash scripts/get_model.sh`."
        )

    interpreter = Interpreter(model_path=str(model_path))
    interpreter.allocate_tensors()
    return interpreter, _load_labels(labels_path)


def _load_labels(path: Path) -> dict[int, str]:
    """Parse a line-indexed labels file. Handles both 'name' and '<idx> name' lines."""
    labels: dict[int, str] = {}
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines()):
        if not line.strip():
            continue
        parts = line.split(None, 1)
        if len(parts) == 2 and parts[0].isdigit():
            labels[int(parts[0])] = parts[1].strip()
        else:
            labels[i] = line.strip()
    return labels


def _is_background(label: str) -> bool:
    return "background" in label.lower()


def _split_label(label: str) -> tuple[str, str | None]:
    """'Turdus migratorius (American Robin)' -> ('American Robin', 'Turdus migratorius')."""
    label = label.strip()
    if "(" in label and label.endswith(")"):
        sci, _, rest = label.partition("(")
        common = rest[:-1].strip()
        sci = sci.strip()
        return (common or sci), (sci or None)
    return label, None


def _predict(interpreter, jpeg_bytes: bytes) -> tuple[int, float]:
    """Return (class_index, confidence) for one frame."""
    image = Image.open(BytesIO(jpeg_bytes)).convert("RGB").resize(
        (INPUT_SIZE, INPUT_SIZE), Image.BILINEAR
    )
    arr = np.asarray(image)

    inp = interpreter.get_input_details()[0]
    out = interpreter.get_output_details()[0]

    if inp["dtype"] == np.uint8:
        data = arr.astype(np.uint8)
    else:
        data = arr.astype(np.float32) / 255.0

    interpreter.set_tensor(inp["index"], data[None, ...])
    interpreter.invoke()
    scores = interpreter.get_tensor(out["index"])[0]

    # Dequantize a uint8 output back to probabilities.
    if out["dtype"] == np.uint8:
        scale, zero_point = out["quantization"]
        scores = (scores.astype(np.float32) - zero_point) * scale

    idx = int(np.argmax(scores))
    return idx, float(scores[idx])


def analyze(frames: list[bytes]) -> BirdAnalysis:
    interpreter, labels = _load()

    # Best confidence seen per species across all frames.
    best: dict[str, tuple[float, str | None]] = {}
    for jpeg in frames:
        idx, conf = _predict(interpreter, jpeg)
        label = labels.get(idx, f"class {idx}")
        if _is_background(label):
            continue
        common, sci = _split_label(label)
        if common not in best or conf > best[common][0]:
            best[common] = (conf, sci)

    if not best:
        return BirdAnalysis(
            is_bird_present=False, species=[], summary="No bird detected."
        )

    species = [
        SpeciesSighting(
            common_name=common,
            scientific_name=sci,
            confidence=conf,
            count=1,
            field_marks="identified by local classifier",
        )
        for common, (conf, sci) in sorted(best.items(), key=lambda kv: -kv[1][0])
    ]
    top = species[0]
    return BirdAnalysis(
        is_bird_present=True,
        species=species,
        summary=f"Local model: {top.common_name} ({top.confidence:.0%} confidence).",
    )
