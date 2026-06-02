"""Monthly incident solar radiation map (SOL).

SOL(x, t) = GHI * 3.6 * (1 + VAR_PCT_MES[t]/100) * n_dias(t)

GHI is the Global Solar Atlas baseline in kWh/m2/day; the 3.6 factor converts
kWh -> MJ. VAR_PCT_MES is the monthly percentage deviation vs annual mean
(from CAMS for a regional reference point — applied uniformly, a known limit).
Output unit: MJ/m2/month.
"""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

FloatArray = NDArray[np.floating]

KWH_TO_MJ = 3.6


def sol(ghi_base: FloatArray, var_pct_mes: float, n_dias: int) -> FloatArray:
    """Monthly SOL in MJ/m2/month from daily GHI (kWh/m2/day)."""
    ghi = np.asarray(ghi_base, dtype=np.float64)
    return ghi * KWH_TO_MJ * (1.0 + var_pct_mes / 100.0) * n_dias
