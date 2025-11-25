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

