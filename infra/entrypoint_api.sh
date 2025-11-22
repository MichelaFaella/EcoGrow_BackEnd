#!/usr/bin/env bash
set -e

# Warm caches; no-op if already present
python /app/infra/warm_assets.py || true

exec "$@"
