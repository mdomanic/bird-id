# Bird ID — Arlo bird-species monitor

Watches your Arlo camera(s) for motion, downloads each recorded clip, and uses
**Claude's vision API** to identify any bird species in the footage. Confident
sightings are logged to a database, the frame is saved, you get a desktop/email
notification, and everything shows up on a small local web dashboard.

```
motion ─▶ Arlo clip ─▶ sample frames ─▶ Claude vision ─▶ log + image + notify
                                                            └─▶ web dashboard
```

## How it works

| File | Responsibility |
|------|----------------|
| `arlo_client.py` | Log into Arlo (`pyaarlo`), watch for motion, download clips |
| `frames.py` | Sample JPEG frames from a clip (or pass an image through) |
| `identifier.py` | Claude vision call → structured `BirdAnalysis` (species, confidence, field marks) |
| `pipeline.py` | Shared glue: extract → identify → save/log/notify |
| `storage.py` | SQLite log + saved frame images |
| `notifier.py` | Windows desktop toast + optional email |
| `dashboard.py` | Flask web UI (recent sightings + species tally) |
| `main.py` | Live monitor entry point |
| `identify_file.py` | Offline test: run the pipeline on a local image/video |

## Identification engines

Set `BIRD_ID_ENGINE` in `.env` (or from the Settings page):

| Engine | Cost | Output | Notes |
|--------|------|--------|-------|
| **`local`** (default) | **Free** | species + confidence | On-device TFLite classifier (iNaturalist MobileNet, ~960 species). Runs on CPU in milliseconds, fully offline. Download the model once with `scripts/get_model.sh` (the installer does this). |
| `claude` | API credits | species + reasoning + field marks | Claude vision API. More accurate on tricky shots, open-ended species, and gracefully says "that's a squirrel". Needs `ANTHROPIC_API_KEY`. |

Both feed the exact same pipeline (frames → ID → log/notify/dashboard), so you can
switch engines anytime — change `BIRD_ID_ENGINE`, restart the monitor, done.

The local model has no per-image cost but a fixed species list and species-only
output; Claude costs per image but reasons about the scene. Many people run
`local` as the always-on default and only flip to `claude` when they want a
second opinion on something unusual.

## Setup

### 1. Python

> **Recommended: Python 3.11 or 3.12.** This project depends on `pyaarlo` and
> `opencv-python-headless`, which may not yet ship prebuilt wheels for the very
> newest Python (e.g. 3.14). If `pip install` fails to build a package, install
> a 3.11/3.12 interpreter and create the virtual environment with it.

```powershell
cd C:\Users\mattd\OneDrive\Desktop\Bird_ID
py -3.12 -m venv .venv          # or: python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### 2. Configure

```powershell
copy .env.example .env
notepad .env
```

Fill in:

- **`ANTHROPIC_API_KEY`** — from <https://console.anthropic.com/>.
- **Arlo login** (`ARLO_USERNAME`, `ARLO_PASSWORD`).
- **Two-factor auth.** Arlo requires 2FA. The hands-free option is email codes
  read automatically over IMAP — set `ARLO_TFA_*` to the inbox Arlo emails codes
  to. For Gmail, turn on 2-Step Verification and create an **App Password** for
  `ARLO_TFA_PASSWORD` (a normal password won't work over IMAP).
- Optionally `LOCATION_HINT` (improves species accuracy), `ARLO_CAMERAS`
  (names to watch; blank = all), and the email/SMTP fields for email alerts.

### 3. Test the bird-ID before touching Arlo

Confirm your API key and the vision pipeline work using any bird photo or clip:

```powershell
python identify_file.py path\to\some_bird.jpg
```

You should see the identified species printed, an image saved under `captures\`,
and a row added to the database. This path needs **no Arlo configuration**.

### 4. Run the monitor

```powershell
python main.py
```

It logs in, watches for motion, and processes each clip. Stop with **Ctrl+C**.

### 5. View the dashboard

In a second terminal:

```powershell
python dashboard.py
```

Open <http://127.0.0.1:5000/>.

## Deploying on Proxmox (always-on)

Run this on your home server instead of your laptop so it's always watching. Use
a **lightweight LXC container** — a full VM is overkill for a small Python
process whose heavy lifting happens in Claude's cloud.

> On a headless Linux server the Windows desktop toasts don't fire (they're
> skipped silently). Configure the `EMAIL_*` fields in `.env` so you still get
> sighting alerts.

### 1. Create the container (on the Proxmox host)

- Template: **Debian 12** (ships Python 3.11 — clean wheels for `pyaarlo`/OpenCV).
- Size: **1 vCPU, 512 MB–1 GB RAM, ~4 GB disk** (bump disk if you keep many clips).
- Unprivileged container, networking on your LAN with internet access.

You can create it from the Proxmox UI, or from the host shell:

```bash
pct create 110 local:vztmpl/debian-12-standard_*.tar.zst \
  --hostname bird-id --cores 1 --memory 1024 \
  --net0 name=eth0,bridge=vmbr0,ip=dhcp --rootfs local-lvm:4 --unprivileged 1
pct start 110 && pct enter 110
```

### 2. Get the files into the container at `/opt/bird-id`

From inside the container (e.g. `git clone <your repo> /opt/bird-id`), or copy
from your laptop with `scp -r` / the Proxmox host.

### 3. Run the installer

```bash
cd /opt/bird-id
sudo bash deploy/setup.sh
```

This installs dependencies into a venv, creates a `birdid` service user, and
installs two systemd services.

### 4. Configure and start

```bash
nano /opt/bird-id/.env        # API key, Arlo creds, EMAIL_/SMTP_, DASHBOARD_HOST=0.0.0.0
systemctl enable --now bird-id-monitor bird-id-dashboard
```

- **`bird-id-monitor`** — the live watcher (auto-starts on boot, auto-restarts on crash).
- **`bird-id-dashboard`** — the web UI at `http://<container-ip>:5000/`.

### 5. Operate

```bash
journalctl -u bird-id-monitor -f     # follow the monitor logs
systemctl restart bird-id-monitor    # after editing .env
systemctl status bird-id-dashboard
```

## Configuring from the web (Settings page)

Instead of editing `.env` over SSH, you can change everything from the dashboard:
click **⚙️ Settings** (top-right) or go to `http://<server-ip>:5000/settings`.

- **It's password-protected.** Set `DASHBOARD_PASSWORD` in `.env` (or set it from
  the Settings page on first use). Log in with any username and that password.
  Until one is set, the page warns that it's unprotected. The read-only sightings
  view stays open on your LAN.
- **Secrets are write-only.** API key / passwords show as blank with a "● set"
  badge if a value exists; leave them blank to keep the current value, or type a
  new one to replace it. Saving never wipes a secret you left blank.
- **Applying changes.** The monitor runs as a separate service, so after saving,
  click **Restart monitor now** (or run `systemctl restart bird-id-monitor`).
  The button uses a locked-down sudoers rule (`deploy/birdid-sudoers`) that lets
  the dashboard restart *only* that one service. `setup.sh` installs it; if you
  set this up before this feature existed, install it once with:
  ```bash
  install -m 0440 -o root -g root /opt/bird-id/deploy/birdid-sudoers /etc/sudoers.d/birdid
  ```

`DASHBOARD_HOST` / `DASHBOARD_PORT` are deliberately not web-editable (changing
the bind address could lock you out) — edit those in `.env` if needed.

## Tuning (in `.env`)

- `BIRD_ID_MODEL` — `claude-opus-4-8` (default, most accurate). Switch to
  `claude-sonnet-4-6` or `claude-haiku-4-5` to cut cost on a busy camera.
- `FRAMES_PER_CLIP` — frames sent to Claude per event (more = better coverage,
  higher cost). Default 4.
- `MIN_CONFIDENCE` — minimum confidence (0–1) to log/notify. Default 0.4.
- `NOTIFY_MODE` — `new` (only the first time a species appears) or `all`.

## Cost note

Each motion event sends `FRAMES_PER_CLIP` images to Claude. On a busy feeder cam
this adds up. Levers: lower `FRAMES_PER_CLIP`, use a cheaper `BIRD_ID_MODEL`, or
raise the camera's motion sensitivity threshold in the Arlo app so it triggers
less on wind/cars.

## Troubleshooting

- **`pip install` fails building pyaarlo / opencv** — you're likely on a Python
  version without wheels yet. Use Python 3.11 or 3.12 (see Setup step 1).
- **Login fails / asks for 2FA repeatedly** — double-check the `ARLO_TFA_*`
  inbox actually receives Arlo's codes, and that you used an App Password for
  IMAP. pyaarlo caches a session, so transient failures often clear on retry.
- **Motion fires but no clip downloads** — pyaarlo's `last_video` timing varies
  by camera/firmware. Increase `CLIP_READY_DELAY` / `CLIP_FETCH_RETRIES` at the
  top of `arlo_client.py`. Some Arlo models also need "record on motion" enabled
  (not just "notify") in a mode/rule in the Arlo app, or there's no clip to fetch.
- **No desktop notifications** — `winotify` is Windows-only and installed via
  `requirements.txt`; notifications are best-effort and never block monitoring.
- **Reading clips needs OpenCV** — if you only ever feed images, OpenCV is
  optional; for video clips install `opencv-python-headless`.

## Notes & limitations

- Arlo has no official public API; `pyaarlo` reverse-engineers the cloud API and
  can break when Arlo changes things. This is unofficial and for personal use.
- Identification is only as good as the frame: distant, blurry, or backlit birds
  get low confidence (by design) rather than confident guesses.
- Secrets live in `.env` — keep it out of version control.
