"""Warm up all model assets needed for offline inference.

- Ensures rembg's U2Net weights are cached (respects U2NET_HOME/XDG_CACHE_HOME).
- Ensures MobileCLIP weights are cached (respects ECOGROW_MODEL_CACHE/ECOGROW_CLIP_PRETRAINED).
"""

from __future__ import annotations

import os
from pathlib import Path
import sys
# Ensure project root is on sys.path when invoked as a script.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import numpy as np
from PIL import Image

from disease_detection.models.checkpoint_cache import ensure_mobileclip_checkpoint


def _warm_rembg_cache() -> Path:
    """Trigger rembg to download/cache the U2Net model if missing."""
    from rembg import remove

    # rembg handles caching internally; a dummy call forces the download if needed.
    dummy = Image.fromarray(np.zeros((32, 32, 3), dtype=np.uint8))
    remove(dummy)

    # Resolve cache path for logging.
    u2net_home = os.environ.get("U2NET_HOME")
    if u2net_home:
        return Path(u2net_home)
    return Path.home() / ".u2net"


def _warm_mobileclip_cache() -> str:
    """Download the MobileCLIP checkpoint if not already cached."""
    model_name = os.environ.get("ECOGROW_CLIP_MODEL_NAME", "MobileCLIP-S1")
    # ensure_mobileclip_checkpoint is idempotent and honors ECOGROW_MODEL_CACHE/ECOGROW_CLIP_PRETRAINED.
    return ensure_mobileclip_checkpoint(model_name)


def main() -> None:
    clip_path = _warm_mobileclip_cache()
    u2net_path = _warm_rembg_cache()
    print(f"[warm_assets] MobileCLIP cached at: {clip_path}")
    print(f"[warm_assets] rembg cached at: {u2net_path}")


if __name__ == "__main__":
    main()

