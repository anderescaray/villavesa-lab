"""Planar geometry: EPSG:25830 projection and monotone stop-to-shape projection."""

from __future__ import annotations

from functools import lru_cache

import numba as nb
import numpy as np
import numpy.typing as npt
from pyproj import Transformer

F64 = npt.NDArray[np.float64]

#: Metric CRS used for every distance computation (ETRS89 / UTM 30N).
METRIC_CRS = "EPSG:25830"


@lru_cache(maxsize=2)
def _transformer(inverse: bool) -> Transformer:
    src, dst = ("EPSG:4326", METRIC_CRS) if not inverse else (METRIC_CRS, "EPSG:4326")
    return Transformer.from_crs(src, dst, always_xy=True)


def to_xy(lon: npt.ArrayLike, lat: npt.ArrayLike) -> tuple[F64, F64]:
    """WGS84 lon/lat → EPSG:25830 x/y metres."""
    x, y = _transformer(False).transform(
        np.asarray(lon, dtype=np.float64), np.asarray(lat, dtype=np.float64)
    )
    return np.asarray(x, dtype=np.float64), np.asarray(y, dtype=np.float64)


def to_lonlat(x: npt.ArrayLike, y: npt.ArrayLike) -> tuple[F64, F64]:
    """EPSG:25830 x/y → WGS84 lon/lat."""
    lon, lat = _transformer(True).transform(
        np.asarray(x, dtype=np.float64), np.asarray(y, dtype=np.float64)
    )
    return np.asarray(lon, dtype=np.float64), np.asarray(lat, dtype=np.float64)


def cumulative_length(x: F64, y: F64) -> F64:
    """Cumulative distance (m) along a polyline, starting at 0."""
    out = np.zeros(len(x), dtype=np.float64)
    if len(x) > 1:
        np.cumsum(np.hypot(np.diff(x), np.diff(y)), out=out[1:])
    return out


@nb.njit(cache=True)
def _monotone_dp(cost: npt.NDArray[np.float64]) -> npt.NDArray[np.int64]:  # pragma: no cover
    """Choose one column per row, non-decreasing across rows, minimising total cost.

    ``cost[k, i]`` is the distance of stop ``k`` to segment ``i``. Ties prefer the
    earliest segment. Runs in O(K·M).
    """
    k_n, m_n = cost.shape
    acc = cost[0].copy()
    arg = np.zeros((k_n, m_n), dtype=np.int64)
    for k in range(1, k_n):
        new = np.empty(m_n)
        best = np.inf
        best_j = 0
        for i in range(m_n):
            if acc[i] < best:
                best = acc[i]
                best_j = i
            new[i] = cost[k, i] + best
            arg[k, i] = best_j
        acc = new
    choice = np.empty(k_n, dtype=np.int64)
    best = np.inf
    best_i = 0
    for i in range(m_n):
        if acc[i] < best:
            best = acc[i]
            best_i = i
    choice[k_n - 1] = best_i
    for k in range(k_n - 1, 0, -1):
        choice[k - 1] = arg[k, choice[k]]
    return choice


def project_monotone(
    line_x: F64, line_y: F64, pts_x: F64, pts_y: F64
) -> tuple[F64, F64]:
    """Project an ordered sequence of points onto a polyline, monotonically.

    Each point's projection is constrained to lie at or after the previous one along the
    line; among all monotone assignments the one minimising the sum of point–line
    distances is chosen (dynamic programming over segments). This is robust to loops,
    out-and-back shapes and self-overlapping lines, where a greedy nearest-segment
    projection jumps to the wrong pass.

    Returns:
        ``(offsets_m, distances_m)``: distance along the line of each projection
        (non-decreasing) and the perpendicular distance of each point to it.
    """
    n_pts = len(pts_x)
    cum = cumulative_length(line_x, line_y)
    if len(line_x) < 2 or n_pts == 0:
        d = np.hypot(pts_x - (line_x[0] if len(line_x) else 0.0), pts_y - (line_y[0] if len(line_y) else 0.0))
        return np.zeros(n_pts), d
    ax, ay = line_x[:-1], line_y[:-1]
    dx, dy = np.diff(line_x), np.diff(line_y)
    seg2 = dx * dx + dy * dy
    safe = np.where(seg2 > 0, seg2, 1.0)
    px = pts_x[:, None]
    py = pts_y[:, None]
    t = ((px - ax) * dx + (py - ay) * dy) / safe
    t = np.clip(np.where(seg2 > 0, t, 0.0), 0.0, 1.0)
    qx = ax + t * dx
    qy = ay + t * dy
    dist = np.hypot(px - qx, py - qy)
    choice = _monotone_dp(dist)
    rows = np.arange(n_pts)
    seg_len = np.sqrt(seg2)
    offsets = cum[choice] + t[rows, choice] * seg_len[choice]
    offsets = np.maximum.accumulate(offsets)
    return offsets, dist[rows, choice]
