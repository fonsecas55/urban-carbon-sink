"""Water Stress Coefficient from Sentinel-2 SWIR bands.

Wu et al. 2022 (GMD), eq. 3-5. SIMI bounds are 2nd/98th percentiles over a
large historical sample (NOT per image) and injected as parameters.
"""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

FloatArray = NDArray[np.floating]

S2_REFLECTANCE_SCALE = 10000.0


def simi(b11: FloatArray, b12: FloatArray, scale: float = S2_REFLECTANCE_SCALE) -> FloatArray:
    """SIMI = 0.7071 * sqrt(SWIR1^2 + SWIR2^2).

    B11 (~1610 nm) and B12 (~2190 nm) are divided by `scale` to reach [0, 1]
    reflectance first. Pass `scale=1.0` if the inputs are already reflectance.
    """
    swir1 = np.asarray(b11, dtype=np.float64) / scale
    swir2 = np.asarray(b12, dtype=np.float64) / scale
    return 0.7071 * np.sqrt(swir1**2 + swir2**2)


def wsc(
    b11: FloatArray,
    b12: FloatArray,
    simi_min: float,
    simi_max: float,
    scale: float = S2_REFLECTANCE_SCALE,
) -> FloatArray:
    """WSC = 0.5 + 0.5 * (1 - NSIMI), in [0.5, 1].

    NSIMI = (SIMI - simi_min) / (simi_max - simi_min), clamped to [0, 1] so the
    output stays within the physical [0.5, 1] band even for out-of-sample SIMI.
    """
    s = simi(b11, b12, scale=scale)
    span = simi_max - simi_min
    if span == 0:
        nsimi = np.zeros(s.shape, dtype=np.float64)
    else:
        nsimi = np.clip((s - simi_min) / span, 0.0, 1.0)
    return 0.5 + 0.5 * (1.0 - nsimi)
