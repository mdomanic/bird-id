"""Arlo cloud access via pyaarlo: log in, watch for motion, fetch the clip.

Arlo has no official public API, so this uses the community `pyaarlo` library,
which logs into your Arlo cloud account and reverse-engineers its API. Login
requires two-factor auth; the easiest unattended option is email codes read over
IMAP (configure ARLO_TFA_* in .env).

Behaviour: when a camera reports motion, we wait briefly for Arlo's cloud to
finish the recording, download the resulting MP4 to data/clips/, and hand the
path to a callback you provide.

NOTE: pyaarlo's exact attribute/method behaviour varies by camera model and
firmware. The motion -> last_video flow below works for most cameras, but if
clips don't download for yours, see the troubleshooting notes in the README.
"""
from __future__ import annotations

import threading
import time
from pathlib import Path
from queue import Queue
from typing import Callable

from config import CLIPS_DIR, settings

# How long to wait after motion before asking for the recorded clip. Arlo needs
# a few seconds to finish uploading the recording to its cloud.
CLIP_READY_DELAY = 12
# How many times to re-check for the clip before giving up.
CLIP_FETCH_RETRIES = 5
CLIP_FETCH_INTERVAL = 4


def build_arlo():
    """Create and return an authenticated PyArlo client."""
    try:
        from pyaarlo import PyArlo
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "pyaarlo is not installed. Run `pip install pyaarlo`."
        ) from exc

    if not (settings.arlo_username and settings.arlo_password):
        raise RuntimeError("ARLO_USERNAME / ARLO_PASSWORD are not set in .env")

    kwargs = dict(
        username=settings.arlo_username,
        password=settings.arlo_password,
        tfa_type=settings.arlo_tfa_type,
        tfa_source=settings.arlo_tfa_source,
    )
    # Only pass IMAP details when using email-over-IMAP 2FA.
    if settings.arlo_tfa_source == "imap":
        kwargs.update(
            tfa_host=settings.arlo_tfa_host,
            tfa_port=settings.arlo_tfa_port,
            tfa_username=settings.arlo_tfa_username,
            tfa_password=settings.arlo_tfa_password,
        )
    return PyArlo(**kwargs)


def _select_cameras(arlo) -> list:
    cameras = list(arlo.cameras)
    wanted = settings.arlo_cameras
    if not wanted:
        return cameras
    selected = [c for c in cameras if c.name in wanted]
    missing = set(wanted) - {c.name for c in cameras}
    if missing:
        print(f"[arlo] cameras not found and skipped: {', '.join(sorted(missing))}")
    return selected


def _download_clip(camera, event_id: str) -> Path | None:
    """Try to download the most recent recording for a camera."""
    for attempt in range(CLIP_FETCH_RETRIES):
        try:
            video = camera.last_video  # pyaarlo ArloVideo, or None
        except Exception as exc:
            print(f"[arlo] last_video error for {camera.name}: {exc}")
            video = None

        if video is not None:
            dest = CLIPS_DIR / f"{event_id}.mp4"
            try:
                video.download_video(str(dest))
                if dest.exists() and dest.stat().st_size > 0:
                    return dest
            except Exception as exc:
                print(f"[arlo] download failed for {camera.name}: {exc}")
        time.sleep(CLIP_FETCH_INTERVAL)
    print(f"[arlo] no clip retrieved for {camera.name} (event {event_id[:8]})")
    return None


class ArloWatcher:
    """Subscribes to motion events and feeds downloaded clips to a callback."""

    def __init__(self, on_clip: Callable[[Path, str], None]):
        self.on_clip = on_clip
        self._queue: "Queue[tuple]" = Queue()
        self._stop = threading.Event()
        self._arlo = None

    def _on_motion(self, device, attr, value):
        if attr == "motionDetected" and value:
            print(f"[arlo] motion on {device.name}")
            self._queue.put((device, time.time()))

    def _worker(self):
        import uuid

        while not self._stop.is_set():
            try:
                device, detected_at = self._queue.get(timeout=1)
            except Exception:
                continue

            # Wait for Arlo to finish the recording.
            wait = CLIP_READY_DELAY - (time.time() - detected_at)
            if wait > 0:
                time.sleep(wait)

            event_id = uuid.uuid4().hex
            clip = _download_clip(device, event_id)
            source = f"{device.name}"
            try:
                if clip is not None:
                    self.on_clip(clip, source)
            except Exception as exc:
                print(f"[arlo] processing error for {source}: {exc}")

    def run(self):
        """Block, watching for motion until interrupted."""
        self._arlo = build_arlo()
        cameras = _select_cameras(self._arlo)
        if not cameras:
            raise RuntimeError("No matching Arlo cameras found.")

        print(f"[arlo] watching {len(cameras)} camera(s): "
              f"{', '.join(c.name for c in cameras)}")
        for camera in cameras:
            camera.add_attr_callback("motionDetected", self._on_motion)

        worker = threading.Thread(target=self._worker, daemon=True)
        worker.start()

        try:
            while not self._stop.is_set():
                time.sleep(1)
        except KeyboardInterrupt:
            print("\n[arlo] stopping ...")
        finally:
            self._stop.set()

    def stop(self):
        self._stop.set()
