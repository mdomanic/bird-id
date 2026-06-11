"""Schema for the web settings page: which .env keys are editable, how to render
them, and how to validate submitted values.

`DASHBOARD_HOST` / `DASHBOARD_PORT` are intentionally NOT editable here — changing
the bind address from the web UI could lock you out of the dashboard. Edit those
in .env directly if you need to.
"""
from __future__ import annotations

from dataclasses import dataclass, field as dc_field

MODELS = ["claude-opus-4-8", "claude-sonnet-4-6", "claude-haiku-4-5"]


@dataclass(frozen=True)
class Field:
    key: str
    label: str
    type: str = "text"           # text | password | int | float | select
    help: str = ""
    options: list[str] = dc_field(default_factory=list)
    minimum: float | None = None
    maximum: float | None = None


# Ordered list of (section title, [fields]).
SECTIONS: list[tuple[str, list[Field]]] = [
    ("Engine", [
        Field("BIRD_ID_ENGINE", "ID engine", "select",
              "local = free on-device classifier; ollama = local vision-LLM; "
              "claude = API (needs credits).",
              options=["local", "ollama", "claude"]),
    ]),
    ("Ollama (only used when engine = ollama)", [
        Field("OLLAMA_URL", "Ollama URL", "text",
              "e.g. http://192.168.1.60:11434 — the box running Ollama."),
        Field("OLLAMA_MODEL", "Vision model", "text",
              "e.g. llama3.2-vision, qwen2.5vl:7b, moondream."),
        Field("OLLAMA_TIMEOUT", "Timeout (seconds)", "int",
              "Max wait per image. CPU inference can be slow.",
              minimum=10, maximum=1200),
    ]),
    ("Claude (only used when engine = claude)", [
        Field("ANTHROPIC_API_KEY", "Anthropic API key", "password",
              "From console.anthropic.com. Only needed for the claude engine."),
        Field("BIRD_ID_MODEL", "Model", "select",
              "Opus is most accurate; Sonnet/Haiku are cheaper.", options=MODELS),
        Field("LOCATION_HINT", "Location hint", "text",
              "e.g. 'Portland, Oregon, USA'. Improves species accuracy."),
    ]),
    ("Arlo account", [
        Field("ARLO_USERNAME", "Arlo email", "text"),
        Field("ARLO_PASSWORD", "Arlo password", "password"),
        Field("ARLO_CAMERAS", "Cameras to watch", "text",
              "Comma-separated camera names. Leave blank to watch all."),
    ]),
    ("Arlo two-factor (email over IMAP)", [
        Field("ARLO_TFA_TYPE", "2FA type", "select", options=["email"]),
        Field("ARLO_TFA_SOURCE", "2FA source", "select", options=["imap"]),
        Field("ARLO_TFA_HOST", "IMAP host", "text", "e.g. imap.gmail.com"),
        Field("ARLO_TFA_PORT", "IMAP port", "int", "Usually 993.",
              minimum=1, maximum=65535),
        Field("ARLO_TFA_USERNAME", "IMAP username", "text",
              "The inbox that receives Arlo's 2FA codes."),
        Field("ARLO_TFA_PASSWORD", "IMAP password", "password",
              "App password for that inbox (not your normal login)."),
    ]),
    ("Detection", [
        Field("FRAMES_PER_CLIP", "Frames per clip", "int",
              "How many frames per motion event to send to Claude.",
              minimum=1, maximum=12),
        Field("MIN_CONFIDENCE", "Minimum confidence", "float",
              "0.0-1.0. Sightings below this are ignored.",
              minimum=0.0, maximum=1.0),
        Field("NOTIFY_MODE", "Notify mode", "select",
              "'new' = only first sighting of a species; 'all' = every detection.",
              options=["new", "all"]),
    ]),
    ("Email alerts", [
        Field("EMAIL_TO", "Send alerts to", "text",
              "Leave blank to disable email alerts."),
        Field("SMTP_HOST", "SMTP host", "text", "e.g. smtp.gmail.com"),
        Field("SMTP_PORT", "SMTP port", "int", "Usually 587.",
              minimum=1, maximum=65535),
        Field("SMTP_USERNAME", "SMTP username", "text"),
        Field("SMTP_PASSWORD", "SMTP password", "password",
              "App password for the sending account."),
    ]),
    ("Dashboard", [
        Field("DASHBOARD_PASSWORD", "Settings password", "password",
              "Protects this settings page. Takes effect immediately."),
    ]),
]


def iter_fields():
    for _, fields in SECTIONS:
        for f in fields:
            yield f


def collect_updates(form) -> tuple[dict[str, str], list[str]]:
    """Validate a submitted form; return (changes, errors).

    Password fields left blank are skipped (keep current value). Other fields
    may be cleared. Numeric fields are range-checked.
    """
    changes: dict[str, str] = {}
    errors: list[str] = []

    for f in iter_fields():
        raw = form.get(f.key, "")
        value = raw.strip()

        if f.type == "password":
            if value == "":
                continue  # leave the existing secret untouched

        if f.type in ("int", "float"):
            if value == "":
                errors.append(f"{f.label} is required.")
                continue
            try:
                num = int(value) if f.type == "int" else float(value)
            except ValueError:
                errors.append(f"{f.label} must be a number.")
                continue
            if f.minimum is not None and num < f.minimum:
                errors.append(f"{f.label} must be at least {f.minimum}.")
                continue
            if f.maximum is not None and num > f.maximum:
                errors.append(f"{f.label} must be at most {f.maximum}.")
                continue
            value = str(num)

        if f.type == "select" and f.options and value not in f.options:
            errors.append(f"{f.label} has an invalid value.")
            continue

        changes[f.key] = value

    return changes, errors
