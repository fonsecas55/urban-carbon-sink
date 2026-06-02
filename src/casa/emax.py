"""Maximum light-use efficiency (epsilon_max) per canonical land-cover class.

The lookup table (canonical code -> g C/MJ) is injected from config
(`config/epsilon_max/{xu2023,relatorio}.yml`). Non-vegetation (code 0) maps to
0, which masks NPP there. The module never sees Dynamic World / ESA codes —
only canonical codes from `casa.landcover`.
"""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

FloatArray = NDArray[np.floating]

N_CANONICAL_CLASSES = 6


def table_to_array(table: dict[int, float]) -> NDArray[np.float64]:
    """Build a length-6 lookup array indexed by canonical code.

    Missing codes default to 0.0 (treated as non-vegetation / masked).
    """
    arr = np.zeros(N_CANONICAL_CLASSES, dtype=np.float64)
    for code, value in table.items():
        arr[code] = value
    return arr


def emax(canonical: NDArray[np.uint8], table: dict[int, float]) -> FloatArray:
    """Per-pixel epsilon_max (g C/MJ) by indexing the table with canonical codes."""
    lookup = table_to_array(table)
    return lookup[np.asarray(canonical)]
