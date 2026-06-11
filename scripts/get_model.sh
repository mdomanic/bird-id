#!/usr/bin/env bash
#
# Download the free local bird-classification model + labels into models/.
# These are the iNaturalist-trained MobileNet classifier and label map from
# Google Coral's public test_data repo (no account needed).
#
#     bash scripts/get_model.sh
#
set -euo pipefail

DIR="$(cd "$(dirname "$0")/.." && pwd)/models"
mkdir -p "$DIR"

MODEL_URL="https://github.com/google-coral/test_data/raw/master/mobilenet_v2_1.0_224_inat_bird_quant.tflite"
LABELS_URL="https://github.com/google-coral/test_data/raw/master/inat_bird_labels.txt"

fetch() {
  url="$1"; out="$2"
  if command -v curl >/dev/null 2>&1; then
    curl -fSL "$url" -o "$out"
  elif command -v wget >/dev/null 2>&1; then
    wget -qO "$out" "$url"
  else
    echo "Need curl or wget installed." >&2
    exit 1
  fi
}

echo "==> Downloading bird model -> $DIR/birds.tflite"
fetch "$MODEL_URL" "$DIR/birds.tflite"
echo "==> Downloading labels      -> $DIR/birds_labels.txt"
fetch "$LABELS_URL" "$DIR/birds_labels.txt"
echo "Done. $(wc -l < "$DIR/birds_labels.txt") labels loaded."
