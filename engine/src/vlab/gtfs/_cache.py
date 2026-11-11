"""On-disk cache location and content hashing shared by the GTFS and walk layers."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import numpy as np
import numpy.typing as npt

_ENV_VAR = "VLAB_CACHE_DIR"


def default_cache_dir() -> Path:
    """Return the cache directory (``$VLAB_CACHE_DIR`` or ``<repo>/data/cache``).

    The repository root is located from this file (``engine/src/vlab/gtfs``). When the
    package is installed elsewhere (no ``data/`` folder next to the source tree), the
    cache falls back to ``~/.cache/vlab``.
    """
    env = os.environ.get(_ENV_VAR)
    if env:
        return Path(env)
    here = Path(__file__).resolve()
    if len(here.parents) > 4:
        repo = here.parents[4]
        if (repo / "data").is_dir():
            return repo / "data" / "cache"
    return Path.home() / ".cache" / "vlab"


def file_sha256(path: Path, chunk: int = 1 << 20) -> str:
    """SHA-256 hex digest of a file's content."""
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while True:
            block = fh.read(chunk)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def arrays_digest(*arrays: npt.ArrayLike, extra: str = "") -> str:
    """Stable SHA-256 digest of numpy arrays (dtype, shape and bytes) plus a string."""
    h = hashlib.sha256()
    for a in arrays:
        arr = np.ascontiguousarray(a)
        h.update(str(arr.dtype).encode())
        h.update(str(arr.shape).encode())
        h.update(arr.tobytes())
    h.update(extra.encode())
    return h.hexdigest()
