#!/usr/bin/env bash
set -euo pipefail

REPO_URL=$1
REGION="${AWS_DEFAULT_REGION:-us-east-1}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

if [[ ! -f "$PROJECT_ROOT/lambda/model.pkl" ]]; then
  echo "ERROR: lambda/model.pkl not found. Run scripts/download_model.sh first."
  exit 1
fi

echo "Logging into ECR..."
MSYS_NO_PATHCONV=1 aws ecr get-login-password --region "$REGION" \
  | docker login --username AWS --password-stdin "$REPO_URL"

echo "Building and pushing Docker image..."
docker buildx build \
  --platform linux/amd64 \
  --provenance=false \
  --push \
  -t "$REPO_URL:latest" \
  "$PROJECT_ROOT/lambda/"

echo "Done: $REPO_URL:latest"
