"""Final CASA integration: NPP and its conversion to absolute CO2 tonnes.

Pure, per-pixel array math. The functions here operate on one block of arrays
(one window's worth of the already-computed term maps) and never read I/O nor
accumulate across windows — the orchestrator (`pipeline.py`) sums the partial
per-window totals to obtain the regional figure without exhausting RAM.

CASA equation (docs/casa-model.md, eq. 1):
    NPP = PAR_FRACTION * SOL * FPAR * epsilon_max * T_eps1 * T_eps2 * WSC
"""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

FloatArray = NDArray[np.floating]

PAR_FRACTION = 0.5
CO2_PER_C = 44.0 / 12.0  # ~= 3.67, molar mass ratio CO2 / C
GRAMS_PER_TONNE = 1e6


def npp(
    sol: FloatArray,
    fpar: FloatArray,
    emax: FloatArray,
    t_eps1: FloatArray,
    t_eps2: FloatArray,
    wsc: FloatArray,
    par_fraction: float = PAR_FRACTION,
) -> FloatArray:
    """NPP carbon density in g C / m2 / month, per pixel.

    All inputs are broadcastable arrays (or scalars, for T_eps1 / scene-constant
    terms). Non-vegetation pixels carry emax = 0 and therefore yield NPP = 0.
    """
    return (
        par_fraction
        * np.asarray(sol, dtype=np.float64)
        * np.asarray(fpar, dtype=np.float64)
        * np.asarray(emax, dtype=np.float64)
        * np.asarray(t_eps1, dtype=np.float64)
        * np.asarray(t_eps2, dtype=np.float64)
        * np.asarray(wsc, dtype=np.float64)
    )


def npp_c_to_co2(npp_c: FloatArray) -> FloatArray:
    """Convert carbon density to CO2 density (same units), via 44/12."""
    return np.asarray(npp_c, dtype=np.float64) * CO2_PER_C


def density_to_tonnes(density: FloatArray, area_pixel_m2: float) -> FloatArray:
    """Convert a g/m2/month density map to absolute tonnes per pixel.

    tonnes_pixel = density [g/m2] * area_pixel_m2 [m2] / 1e6 [g/t].

    This is the per-pixel array form; the pipeline sums the result over valid
    pixels (and across windows) to get the regional total. Sentinel-2 native
    grid is 10x10 m, so `area_pixel_m2 = 100`. The legacy code divided by 1e6
    WITHOUT multiplying by area, undercounting by the pixel area factor.
    """
    return np.asarray(density, dtype=np.float64) * area_pixel_m2 / GRAMS_PER_TONNE
