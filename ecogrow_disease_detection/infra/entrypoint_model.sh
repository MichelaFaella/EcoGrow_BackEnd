#!/usr/bin/env bash
set -e

# Ensure cache directories exist
mkdir -p /app/artifacts/detectors /app/artifacts/pretrained "${U2NET_HOME:-/app/artifacts/u2net}"

# Warm caches (best effort; do not fail the container on download issues)
python /app/infra/warm_assets.py || true

exec "$@"

