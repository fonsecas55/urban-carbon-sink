"""NDVI and Simple Ratio from Sentinel-2 red/NIR reflectance.

Pure, vectorised array math. No I/O, no windowing — callers feed NumPy arrays
(read per window upstream) and accumulate results downstream.
"""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

FloatArray = NDArray[np.floating]


def ndvi(red: FloatArray, nir: FloatArray) -> FloatArray:
    """NDVI = (NIR - RED) / (NIR + RED), in [-1, 1].

    `red` = Sentinel-2 B4, `nir` = B8, as reflectance (scale is irrelevant —
    the ratio cancels it). Pixels where NIR + RED == 0 yield 0, not NaN.
    """
    red = np.asarray(red, dtype=np.float64)
    nir = np.asarray(nir, dtype=np.float64)
    denom = nir + red
    out = np.zeros(np.broadcast(red, nir).shape, dtype=np.float64)
    np.divide(nir - red, denom, out=out, where=denom != 0)
    return out


def simple_ratio(ndvi_values: FloatArray) -> FloatArray:
    """SR = (1 + NDVI) / (1 - NDVI). Xu et al. 2023, eq. 4.

    NDVI == 1 would divide by zero; such pixels are clamped just below 1 first.
    """
    nd = np.clip(np.asarray(ndvi_values, dtype=np.float64), -0.999999, 0.999999)
    return (1.0 + nd) / (1.0 - nd)
