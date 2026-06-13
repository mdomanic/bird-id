"""Local web dashboard for browsing bird sightings and editing configuration.

    python dashboard.py

Then open http://127.0.0.1:5000/ (host/port configurable in .env).

The /settings page edits .env and is protected by Basic Auth using
DASHBOARD_PASSWORD. The read-only sightings views are open on your LAN.
"""
from __future__ import annotations

import hmac
import subprocess
from functools import wraps
from pathlib import Path

from flask import (
    Flask, Response, abort, flash, jsonify, redirect, render_template,
    request, send_file, url_for,
)

from config import CAPTURES_DIR, settings
from envfile import read_env, update_env
from storage import (
    confirmed_species, recent_sightings, set_feedback, species_tally,
)
from webconfig import SECTIONS, collect_updates

app = Flask(__name__)
# Needed only for flashed messages on the settings page.
app.secret_key = "bird-id-dashboard"  # not security-sensitive (no user sessions)


# --- Auth --------------------------------------------------------------------

def _current_password() -> str:
    """Read the dashboard password fresh from .env each request so changes apply
    immediately without restarting the dashboard."""
    return read_env().get("DASHBOARD_PASSWORD", "") or settings.dashboard_password


def require_auth(view):
    """Protect a view with Basic Auth. If no password is configured, allow access
    (bootstrap mode) so you can set one — the settings page warns about this."""
    @wraps(view)
    def wrapped(*args, **kwargs):
        password = _current_password()
        if password:
            auth = request.authorization
            if not auth or not hmac.compare_digest(auth.password or "", password):
                return Response(
                    "Authentication required.", 401,
                    {"WWW-Authenticate": 'Basic realm="Bird ID settings"'},
                )
        return view(*args, **kwargs)
    return wrapped


# --- Sightings (open) --------------------------------------------------------

@app.route("/")
def index():
    sightings = recent_sightings(limit=100)
    for s in sightings:
        s["image_name"] = Path(s["image_path"]).name if s.get("image_path") else None
    tally = species_tally()
    # Names offered as autocomplete when correcting a sighting.
    species_names = sorted(
        {s["common_name"] for s in tally} | set(confirmed_species())
    )
    return render_template(
        "dashboard.html",
        sightings=sightings,
        tally=tally,
        species_names=species_names,
        confirmed=confirmed_species(),
        location=settings.location_hint,
    )


@app.route("/feedback/<int:sighting_id>", methods=["POST"])
@require_auth
def feedback(sighting_id: int):
    """Record a thumbs-up / correction on a sighting. Confirmed species then
    prime future identifications (see engine_ollama)."""
    verdict = (request.form.get("verdict") or "").strip().lower()
    if verdict not in ("correct", "wrong"):
        abort(400)
    corrected = request.form.get("corrected_common_name", "")
    if verdict == "wrong" and not corrected.strip():
        flash("Enter the correct species when marking a sighting wrong.", "error")
        return redirect(url_for("index") + "#s" + str(sighting_id))

    if set_feedback(sighting_id, verdict, corrected_common=corrected):
        if verdict == "correct":
            flash("Thanks — confirmed. This species now helps guide future IDs.", "ok")
        else:
            flash(f"Thanks — recorded as {corrected.strip()}. It'll now help guide "
                  "future IDs.", "ok")
    else:
        flash("Sighting not found.", "error")
    return redirect(url_for("index") + "#s" + str(sighting_id))


@app.route("/api/sightings")
def api_sightings():
    return jsonify(recent_sightings(limit=500))


@app.route("/api/species")
def api_species():
    return jsonify(species_tally())


@app.route("/image/<path:name>")
def image(name: str):
    target = (CAPTURES_DIR / Path(name).name).resolve()
    if not str(target).startswith(str(CAPTURES_DIR.resolve())) or not target.exists():
        abort(404)
    return send_file(target, mimetype="image/jpeg")


# --- Settings (auth-protected) -----------------------------------------------

@app.route("/settings", methods=["GET", "POST"])
@require_auth
def settings_page():
    if request.method == "POST":
        changes, errors = collect_updates(request.form)
        if errors:
            for err in errors:
                flash(err, "error")
        else:
            update_env(changes)
            flash("Saved. Restart the monitor to apply changes to the camera "
                  "watcher.", "ok")
            return redirect(url_for("settings_page"))

    current = read_env()
    return render_template(
        "settings.html",
        sections=SECTIONS,
        current=current,
        insecure=not _current_password(),
    )


@app.route("/settings/restart", methods=["POST"])
@require_auth
def restart_monitor():
    """Restart the monitor service so saved settings take effect.

    Requires a sudoers rule allowing the dashboard user to run exactly this
    command (see deploy/birdid-sudoers). Falls back to a clear message if not."""
    try:
        result = subprocess.run(
            ["sudo", "-n", "/usr/bin/systemctl", "restart", "bird-id-monitor"],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode == 0:
            flash("Monitor restarted.", "ok")
        else:
            detail = (result.stderr or result.stdout).strip()
            flash(f"Couldn't restart automatically ({detail or 'permission denied'}). "
                  "Run 'systemctl restart bird-id-monitor' on the server.", "error")
    except Exception as exc:
        flash(f"Restart failed: {exc}. Run 'systemctl restart bird-id-monitor' "
              "on the server.", "error")
    return redirect(url_for("settings_page"))


def main() -> int:
    settings.ensure_dirs()
    print(f"Dashboard: http://{settings.dashboard_host}:{settings.dashboard_port}/")
    app.run(host=settings.dashboard_host, port=settings.dashboard_port, debug=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
