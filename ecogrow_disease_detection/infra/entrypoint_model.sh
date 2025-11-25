#!/usr/bin/env bash
set -e

# Ensure cache directories exist
mkdir -p /app/artifacts/detectors /app/artifacts/pretrained

# Warm caches (best effort; do not fail the container on download issues)
python /app/infra/warm_assets.py || true

exec "$@"
