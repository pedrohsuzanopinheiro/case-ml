#!/usr/bin/env bash
set -euo pipefail

_pwd() { pwd -W 2>/dev/null || pwd; }
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && _pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && _pwd)"
LAMBDA_DIR="$PROJECT_ROOT/lambda"
BUILD_DIR="$PROJECT_ROOT/build"
ZIP_PATH="$BUILD_DIR/lambda_package.zip"

if [[ ! -f "$LAMBDA_DIR/model.pkl" ]]; then
  echo "ERROR: model.pkl not found. Run scripts/download_model.sh first."
  exit 1
fi

mkdir -p "$BUILD_DIR"

echo "Building Lambda package via Docker (Amazon Linux 2)..."
docker run --rm \
  --entrypoint bash \
  -v "$LAMBDA_DIR":/var/task \
  -v "$BUILD_DIR":/var/build \
  public.ecr.aws/lambda/python:3.9 \
  -c "
    yum install -y zip --quiet &&
    pip install scikit-learn==1.1.3 pandas==1.5.3 numpy==1.23.5 -t /tmp/pkg --quiet &&
    cp /var/task/handler.py /tmp/pkg/ &&
    cp /var/task/preprocessing.py /tmp/pkg/ &&
    cp /var/task/model.pkl /tmp/pkg/ &&
    find /tmp/pkg -type d -name 'tests' -exec rm -rf {} + 2>/dev/null || true &&
    find /tmp/pkg -type d -name 'test' -exec rm -rf {} + 2>/dev/null || true &&
    find /tmp/pkg -name '*.pyc' -delete &&
    find /tmp/pkg -type d -name '__pycache__' -exec rm -rf {} + 2>/dev/null || true &&
    find /tmp/pkg -type d -name '*.dist-info' -exec rm -rf {} + 2>/dev/null || true &&
    find /tmp/pkg -type d -name '*.egg-info' -exec rm -rf {} + 2>/dev/null || true &&
    rm -rf /tmp/pkg/numpy/core/include &&
    rm -rf /tmp/pkg/numpy/distutils &&
    rm -rf /tmp/pkg/numpy/f2py &&
    rm -rf /tmp/pkg/scipy/linalg/src &&
    rm -rf /tmp/pkg/scipy/sparse/linalg/dsolve/SuperLU &&
    rm -f /var/build/lambda_package.zip &&
    cd /tmp/pkg &&
    zip -r /var/build/lambda_package.zip .
  "

echo "Package built: $ZIP_PATH ($(du -sh "$ZIP_PATH" | cut -f1))"
