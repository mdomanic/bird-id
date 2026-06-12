"""Central configuration, loaded from environment / .env file.

Every other module imports `settings` from here so there is a single source of
truth for paths, credentials, and tunables.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

# Load .env sitting next to this file (if present) before reading os.environ.
BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

# Runtime data directories (created on first use).
DATA_DIR = BASE_DIR / "data"
CAPTURES_DIR = BASE_DIR / "captures"
CLIPS_DIR = DATA_DIR / "clips"
DB_PATH = DATA_DIR / "sightings.db"


def _split_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


@dataclass(frozen=True)
class Settings:
    # Identification engine: "local" (free on-device classifier) or "claude" (API).
    bird_id_engine: str = os.getenv("BIRD_ID_ENGINE", "local")

    # Local engine (TFLite classifier) model + labels.
    bird_model_path: str = os.getenv("BIRD_MODEL_PATH", str(BASE_DIR / "models" / "birds.tflite"))
    bird_labels_path: str = os.getenv("BIRD_LABELS_PATH", str(BASE_DIR / "models" / "birds_labels.txt"))

    # Ollama engine (only used when BIRD_ID_ENGINE=ollama) — local vision-LLM.
    ollama_url: str = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")
    ollama_model: str = os.getenv("OLLAMA_MODEL", "llama3.2-vision")
    ollama_timeout: int = int(os.getenv("OLLAMA_TIMEOUT", "180") or "180")
    # How long Ollama keeps the model loaded in RAM between requests. Default 5m;
    # set longer (e.g. "30m") or "-1" to keep it resident so sparse motion events
    # don't re-pay the cold-load cost each time.
    ollama_keep_alive: str = os.getenv("OLLAMA_KEEP_ALIVE", "30m")

    # Claude engine (only used when BIRD_ID_ENGINE=claude)
    anthropic_api_key: str = os.getenv("ANTHROPIC_API_KEY", "")
    bird_id_model: str = os.getenv("BIRD_ID_MODEL", "claude-opus-4-8")
    location_hint: str = os.getenv("LOCATION_HINT", "")

    # Arlo
    arlo_username: str = os.getenv("ARLO_USERNAME", "")
    arlo_password: str = os.getenv("ARLO_PASSWORD", "")
    arlo_tfa_type: str = os.getenv("ARLO_TFA_TYPE", "email")
    arlo_tfa_source: str = os.getenv("ARLO_TFA_SOURCE", "imap")
    arlo_tfa_host: str = os.getenv("ARLO_TFA_HOST", "")
    arlo_tfa_port: int = int(os.getenv("ARLO_TFA_PORT", "993") or "993")
    arlo_tfa_username: str = os.getenv("ARLO_TFA_USERNAME", "")
    arlo_tfa_password: str = os.getenv("ARLO_TFA_PASSWORD", "")
    arlo_cameras: list[str] = field(default_factory=lambda: _split_csv(os.getenv("ARLO_CAMERAS", "")))

    # Behaviour
    frames_per_clip: int = int(os.getenv("FRAMES_PER_CLIP", "4") or "4")
    min_confidence: float = float(os.getenv("MIN_CONFIDENCE", "0.4") or "0.4")
    notify_mode: str = os.getenv("NOTIFY_MODE", "new").lower()  # "all" | "new"

    # Notifications
    email_to: str = os.getenv("EMAIL_TO", "")
    smtp_host: str = os.getenv("SMTP_HOST", "")
    smtp_port: int = int(os.getenv("SMTP_PORT", "587") or "587")
    smtp_username: str = os.getenv("SMTP_USERNAME", "")
    smtp_password: str = os.getenv("SMTP_PASSWORD", "")

    # Dashboard
    dashboard_host: str = os.getenv("DASHBOARD_HOST", "127.0.0.1")
    dashboard_port: int = int(os.getenv("DASHBOARD_PORT", "5000") or "5000")
    # Password protecting the web settings page (Basic Auth). Blank = unprotected
    # "bootstrap" mode that warns you to set one.
    dashboard_password: str = os.getenv("DASHBOARD_PASSWORD", "")

    def ensure_dirs(self) -> None:
        for d in (DATA_DIR, CAPTURES_DIR, CLIPS_DIR):
            d.mkdir(parents=True, exist_ok=True)


settings = Settings()
