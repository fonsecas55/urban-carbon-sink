"""FPAR from NDVI and Simple Ratio, per canonical land-cover class.

Xu et al. 2023, eq. 3-6. Per-class NDVI/SR bounds are the 5th/95th percentiles
computed once over a large historical sample (NOT per image) and injected as
parameters — keeping the math pure and temporally coherent across months.
"""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

from casa.ndvi import simple_ratio

FloatArray = NDArray[np.floating]

FPAR_MIN = 0.001
FPAR_MAX = 0.95


def _scale(
    value: FloatArray,
    lo: FloatArray,
    hi: FloatArray,
    fpar_min: float,
    fpar_max: float,
) -> FloatArray:
    """Linear rescale of `value` from [lo, hi] to [fpar_min, fpar_max], clamped.

    Where hi == lo (degenerate, e.g. non-vegetation rows of the table), the
    normalised fraction is 0, so the result is `fpar_min`.
    """
    span = hi - lo
    frac = np.zeros(value.shape, dtype=np.float64)
    np.divide(value - lo, span, out=frac, where=span != 0)
    frac = np.clip(frac, 0.0, 1.0)
    return frac * (fpar_max - fpar_min) + fpar_min


def fpar(
    ndvi_values: FloatArray,
    canonical: NDArray[np.uint8],
    ndvi_min_by_class: FloatArray,
    ndvi_max_by_class: FloatArray,
    sr_min_by_class: FloatArray,
    sr_max_by_class: FloatArray,
    fpar_min: float = FPAR_MIN,
    fpar_max: float = FPAR_MAX,
) -> FloatArray:
    """FPAR = 0.5 * (FPAR_NDVI + FPAR_SR).

    The four `*_by_class` arrays are indexed by canonical code (shape (6,)):
    each pixel picks the bound for its own land-cover class. Non-vegetation
    (code 0) is left to be masked downstream by epsilon_max = 0.
    """
    nd = np.asarray(ndvi_values, dtype=np.float64)
    codes = np.asarray(canonical)
    sr = simple_ratio(nd)

    ndvi_min = np.asarray(ndvi_min_by_class, dtype=np.float64)[codes]
    ndvi_max = np.asarray(ndvi_max_by_class, dtype=np.float64)[codes]
    sr_min = np.asarray(sr_min_by_class, dtype=np.float64)[codes]
    sr_max = np.asarray(sr_max_by_class, dtype=np.float64)[codes]

    fpar_ndvi = _scale(nd, ndvi_min, ndvi_max, fpar_min, fpar_max)
    fpar_sr = _scale(sr, sr_min, sr_max, fpar_min, fpar_max)
    return 0.5 * (fpar_ndvi + fpar_sr)
