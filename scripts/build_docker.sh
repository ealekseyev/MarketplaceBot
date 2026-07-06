#!/usr/bin/env bash
# Build the fb-bot Docker image and push to Docker Hub. Run from repo root:
#   DOCKERHUB_USER=myuser ./scripts/build_docker.sh
#   DOCKERHUB_USER=myuser ./scripts/build_docker.sh --no-cache
#
# With sudo, pass the variable explicitly (sudo does not preserve env by default):
#   sudo DOCKERHUB_USER=myuser ./scripts/build_docker.sh
set -euo pipefail

if [[ -z "${DOCKERHUB_USER:-}" ]]; then
  echo "Set DOCKERHUB_USER to your Docker Hub username" >&2
  exit 1
fi

cd "$(dirname "${BASH_SOURCE[0]}")/.."

IMAGE="${DOCKERHUB_USER}/fb-bot:latest"

sudo docker build -f docker/Dockerfile -t "${IMAGE}" "$@" .
sudo docker push "${IMAGE}"
