#!/usr/bin/env bash
set -euo pipefail

# Resolve paths: pwd -W gives Windows-style paths on Git Bash (needed for Docker
# volume mounts on Windows); fall back to plain pwd on WSL/Linux where Docker
# accepts Unix paths directly.
_pwd() { pwd -W 2>/dev/null || pwd; }
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && _pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && _pwd)"

if [[ ! -f "$PROJECT_ROOT/lambda/model.pkl" ]]; then
  echo "ERROR: lambda/model.pkl not found. Run scripts/download_model.sh first."
  exit 1
fi

echo "Running local tests inside Docker (Python 3.11 + scikit-learn 1.1.3)..."

docker run --rm \
  -v "$PROJECT_ROOT/lambda":/var/task \
  -v "$PROJECT_ROOT/tests":/tests \
  python:3.11-slim \
  bash -c "
    pip install moto[dynamodb] boto3 scikit-learn==1.1.3 pandas==1.5.3 \"numpy<2\" --quiet &&
    cd /var/task && PYTHONPATH=/var/task python /tests/test_local.py
  "
