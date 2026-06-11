"""Turn a recorded clip (or a still image) into a small set of JPEG frames.

Arlo motion recordings are short MP4 clips. We sample a handful of frames spread
across the clip so Claude gets several views of whatever triggered the camera,
which greatly improves identification of a bird that may only be sharp/visible in
one frame.

Video decoding uses OpenCV if available; if it isn't installed we fall back to
treating the input as a single image. Plain image inputs (.jpg/.png) are passed
straight through, so the rest of the pipeline never needs to care about source.
"""
from __future__ import annotations

import io
from pathlib import Path

from PIL import Image

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
VIDEO_SUFFIXES = {".mp4", ".mov", ".m4v", ".avi", ".mkv"}

# Cap the longest edge so we don't send needlessly huge images to the API.
MAX_EDGE = 1568


def _encode_jpeg(image: Image.Image) -> bytes:
    image = image.convert("RGB")
    w, h = image.size
    scale = min(1.0, MAX_EDGE / max(w, h))
    if scale < 1.0:
        image = image.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
    buf = io.BytesIO()
    image.save(buf, format="JPEG", quality=88)
    return buf.getvalue()


def _frames_from_image(path: Path) -> list[bytes]:
    with Image.open(path) as img:
        return [_encode_jpeg(img)]


def _frames_from_video(path: Path, count: int) -> list[bytes]:
    try:
        import cv2  # imported lazily so the image path works without OpenCV
    except ImportError as exc:  # pragma: no cover - depends on environment
        raise RuntimeError(
            "Reading video clips requires OpenCV. Install it with "
            "`pip install opencv-python-headless`."
        ) from exc

    capture = cv2.VideoCapture(str(path))
    if not capture.isOpened():
        raise RuntimeError(f"Could not open video: {path}")

    try:
        total = int(capture.get(cv2.CAP_PROP_FRAME_COUNT)) or 0
        frames: list[bytes] = []

        if total <= 0:
            # Some streams don't report a frame count; read sequentially.
            while len(frames) < count:
                ok, frame = capture.read()
                if not ok:
                    break
                frames.append(_bgr_to_jpeg(frame))
            return frames

        # Sample `count` frames evenly across the clip, skipping the very first
        # and last frames which are often blurry/transitional.
        n = min(count, total)
        positions = [int(total * (i + 1) / (n + 1)) for i in range(n)]
        for pos in positions:
            capture.set(cv2.CAP_PROP_POS_FRAMES, pos)
            ok, frame = capture.read()
            if ok:
                frames.append(_bgr_to_jpeg(frame))
        return frames
    finally:
        capture.release()


def _bgr_to_jpeg(frame) -> bytes:
    import cv2

    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    return _encode_jpeg(Image.fromarray(rgb))


def extract_frames(path: str | Path, count: int = 4) -> list[bytes]:
    """Return a list of JPEG-encoded frames (as bytes) from `path`.

    `path` may be an image or a video. `count` is the target number of frames
    for videos; images always yield exactly one frame.
    """
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix in IMAGE_SUFFIXES:
        return _frames_from_image(path)
    if suffix in VIDEO_SUFFIXES:
        return _frames_from_video(path, count)
    # Unknown extension: try image first, then video.
    try:
        return _frames_from_image(path)
    except Exception:
        return _frames_from_video(path, count)
