"""Local web dashboard for browsing bird sightings.

    python dashboard.py

Then open http://127.0.0.1:5000/ (host/port configurable in .env).
"""
from __future__ import annotations

from pathlib import Path

from flask import Flask, abort, jsonify, render_template, send_file

from config import CAPTURES_DIR, settings
from storage import recent_sightings, species_tally

app = Flask(__name__)


@app.route("/")
def index():
    sightings = recent_sightings(limit=100)
    # Expose just the filename so the template can build /image/<name> URLs.
    for s in sightings:
        s["image_name"] = Path(s["image_path"]).name if s.get("image_path") else None
    return render_template(
        "dashboard.html",
        sightings=sightings,
        tally=species_tally(),
        location=settings.location_hint,
    )


@app.route("/api/sightings")
def api_sightings():
    return jsonify(recent_sightings(limit=500))


@app.route("/api/species")
def api_species():
    return jsonify(species_tally())


@app.route("/image/<path:name>")
def image(name: str):
    # Serve only files that live inside the captures directory.
    target = (CAPTURES_DIR / Path(name).name).resolve()
    if not str(target).startswith(str(CAPTURES_DIR.resolve())) or not target.exists():
        abort(404)
    return send_file(target, mimetype="image/jpeg")


def main() -> int:
    settings.ensure_dirs()
    print(f"Dashboard: http://{settings.dashboard_host}:{settings.dashboard_port}/")
    app.run(host=settings.dashboard_host, port=settings.dashboard_port, debug=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
