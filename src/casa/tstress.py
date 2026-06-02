"""Temperature stress scalars T_eps1 and T_eps2.

Potter 1993, adjusted by Wu 2022. T_opt is the climatological optimal growth
temperature per biome (degrees C) — injected, NEVER the scene mean. The legacy
code computed T_opt = mean(LST scene), which collapses the thermal-stress signal.
"""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

FloatArray = NDArray[np.floating]


def t_mean(t_day: FloatArray, t_night: FloatArray) -> FloatArray:
    """Mean land-surface temperature (degrees C) from Sentinel-3 day/night LST."""
    return 0.5 * (np.asarray(t_day, dtype=np.float64) + np.asarray(t_night, dtype=np.float64))


def t_eps1(t_opt: FloatArray) -> FloatArray:
    """Low-temperature stress: 0.8 + 0.02*T_opt - 0.0005*T_opt^2.

    Constant per biome (depends only on the climatological T_opt), so per scene
    it is constant where T_opt is uniform.
    """
    to = np.asarray(t_opt, dtype=np.float64)
    return 0.8 + 0.02 * to - 0.0005 * to**2


def t_eps2(t_mean_values: FloatArray, t_opt: FloatArray) -> FloatArray:
    """High-temperature stress (Potter 1993), per pixel.

    T_eps2 = 1.184 / {[1 + exp(0.2*(T_opt - 10 - T_mean))]
                      * [1 + exp(0.3*(-T_opt - 10 + T_mean))]}
    """
    tm = np.asarray(t_mean_values, dtype=np.float64)
    to = np.asarray(t_opt, dtype=np.float64)
    left = 1.0 + np.exp(0.2 * (to - 10.0 - tm))
    right = 1.0 + np.exp(0.3 * (-to - 10.0 + tm))
    return 1.184 / (left * right)
