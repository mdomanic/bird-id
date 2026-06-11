#!/usr/bin/env bash
#
# Set up an Ollama vision-LLM server for the Bird ID app, on a fresh
# Debian/Ubuntu LXC. Run as root:
#
#     bash setup_ollama.sh [model]
#
# Default model: qwen2.5vl:7b  (override with the first arg or OLLAMA_MODEL env).
#
# NOTE: NUMA core pinning is a Proxmox HOST edit (/etc/pve/lxc/<id>.conf), not
# something this in-container script can do — see the reminder printed at the end.
set -euo pipefail

MODEL="${1:-${OLLAMA_MODEL:-qwen2.5vl:7b}}"

echo "==> Installing prerequisites"
apt-get update
apt-get install -y curl ca-certificates

echo "==> Installing Ollama"
curl -fsSL https://ollama.com/install.sh | sh

echo "==> Configuring Ollama: listen on the LAN, one inference at a time"
mkdir -p /etc/systemd/system/ollama.service.d
cat >/etc/systemd/system/ollama.service.d/override.conf <<'EOF'
[Service]
Environment=OLLAMA_HOST=0.0.0.0
Environment=OLLAMA_NUM_PARALLEL=1
EOF
systemctl daemon-reload
systemctl enable --now ollama
systemctl restart ollama

echo "==> Waiting for Ollama to be ready"
ready=""
for _ in $(seq 1 30); do
  if curl -fsS http://127.0.0.1:11434/api/version >/dev/null 2>&1; then
    ready=1
    break
  fi
  sleep 2
done
if [ -z "$ready" ]; then
  echo "Ollama did not become ready. Check: systemctl status ollama" >&2
  exit 1
fi

echo "==> Pulling vision model: $MODEL  (can be several GB)"
ollama pull "$MODEL"

IP="$(hostname -I | awk '{print $1}')"
cat <<EOF

==> Done.

Ollama is running on:   http://$IP:11434
Model pulled:           $MODEL

Point the Bird ID app at it (Settings page, or .env on the bird-id container):
    BIRD_ID_ENGINE=ollama
    OLLAMA_URL=http://$IP:11434
    OLLAMA_MODEL=$MODEL
...then restart the monitor.

Quick test from your LAN:
    curl http://$IP:11434/api/tags

REMINDER (run on the Proxmox HOST, not in this container): pin this container to
one CPU socket for best speed. Edit /etc/pve/lxc/<CTID>.conf and add:
    lxc.cgroup2.cpuset.cpus: 0-27
    lxc.cgroup2.cpuset.mems: 0
then:  pct reboot <CTID>
EOF
