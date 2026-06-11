#!/usr/bin/env bash
#
# One-shot installer for the Bird ID app inside a Debian/Ubuntu LXC container.
# Run as root from the project directory after the files are in /opt/bird-id:
#
#     cd /opt/bird-id && sudo bash deploy/setup.sh
#
set -euo pipefail

APP_DIR="/opt/bird-id"
APP_USER="birdid"

if [[ "$(pwd)" != "$APP_DIR" ]]; then
  echo "Please place the project at $APP_DIR and run from there."
  echo "  e.g.  git clone <repo> $APP_DIR   (or scp the files there)"
  exit 1
fi

echo "==> Installing system packages"
apt-get update
# python venv/pip + a couple of runtime libs OpenCV needs even in headless form.
apt-get install -y python3 python3-venv python3-pip libglib2.0-0

echo "==> Creating service user '$APP_USER'"
if ! id -u "$APP_USER" >/dev/null 2>&1; then
  useradd --system --home-dir "$APP_DIR" --shell /usr/sbin/nologin "$APP_USER"
fi

echo "==> Creating virtualenv and installing dependencies"
python3 -m venv "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/pip" install --upgrade pip
"$APP_DIR/.venv/bin/pip" install -r "$APP_DIR/requirements.txt"

echo "==> Preparing data directories"
mkdir -p "$APP_DIR/data" "$APP_DIR/captures"

if [[ ! -f "$APP_DIR/.env" ]]; then
  cp "$APP_DIR/.env.example" "$APP_DIR/.env"
  echo "    Created .env from template - EDIT IT before starting the services."
fi

echo "==> Setting ownership"
chown -R "$APP_USER":"$APP_USER" "$APP_DIR"

echo "==> Installing systemd services"
cp "$APP_DIR/deploy/bird-id-monitor.service"   /etc/systemd/system/
cp "$APP_DIR/deploy/bird-id-dashboard.service" /etc/systemd/system/
systemctl daemon-reload

echo "==> Installing sudoers rule (lets the dashboard restart the monitor)"
install -m 0440 -o root -g root "$APP_DIR/deploy/birdid-sudoers" /etc/sudoers.d/birdid

cat <<'EOF'

==> Done.

Next steps:
  1. Edit configuration:        nano /opt/bird-id/.env
       - ANTHROPIC_API_KEY, Arlo creds + ARLO_TFA_*, and the EMAIL_/SMTP_ fields
       - set DASHBOARD_HOST=0.0.0.0   so the dashboard is reachable on your LAN
  2. (Optional) test the pipeline once:
       sudo -u birdid /opt/bird-id/.venv/bin/python /opt/bird-id/identify_file.py some_bird.jpg
  3. Enable + start the services (auto-start on boot, auto-restart on crash):
       systemctl enable --now bird-id-monitor bird-id-dashboard
  4. Watch logs:
       journalctl -u bird-id-monitor -f
  5. Open the dashboard:  http://<container-ip>:5000/

EOF
