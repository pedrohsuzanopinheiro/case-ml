#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEST="$SCRIPT_DIR/../lambda/model.pkl"

if [[ -f "$DEST" ]]; then
  echo "model.pkl already exists at $DEST — skipping download."
  exit 0
fi

MODEL_URL="https://raw.githubusercontent.com/CaioMar/case_software_engineer/master/modelo/model.pkl"
echo "Downloading model from $MODEL_URL ..."
curl -fSL "$MODEL_URL" -o "$DEST"
echo "Saved to $DEST"
