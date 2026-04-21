# Partial mirror of astropy/wcs/_legacy_fallback.py (new file from PR #17201).
# Not the full WCS module; just the fallback helper introduced by the PR.

import warnings
from typing import Mapping


def derive_cdelt_from_cd(header: Mapping) -> tuple[float, float] | None:
    """Derive pseudo-CDELT values from a CD matrix when CDELT is missing.

    Legacy FITS files (mostly pre-2005 archival survey data) may omit
    CDELT1 / CDELT2 keywords and rely entirely on the CD matrix. Standard
    WCS readers then fail to initialize. This helper recovers the
    effective sample-spacing from the CD matrix so the WCS can be built.

    Args:
        header: FITS header-like mapping.

    Returns:
        (cdelt1, cdelt2) tuple if derivable, else None.
    """
    has_cd = all(f"CD{i}_{j}" in header for i in (1, 2) for j in (1, 2))
    if not has_cd:
        return None

    cd11 = float(header["CD1_1"])
    cd12 = float(header["CD1_2"])
    cd21 = float(header["CD2_1"])
    cd22 = float(header["CD2_2"])

    # Standard WCS: CDELTi = sign * sqrt(CDi1^2 + CDi2^2)
    # The sign is that of the diagonal term in CDELT convention.
    import math
    cdelt1 = math.copysign(math.sqrt(cd11 * cd11 + cd12 * cd12), cd11)
    cdelt2 = math.copysign(math.sqrt(cd21 * cd21 + cd22 * cd22), cd22)

    warnings.warn(
        "CDELT keys absent from header; derived from CD matrix. "
        "This is a best-effort fallback for legacy FITS; verify the "
        "resulting WCS on a known reference if precision matters.",
        UserWarning,
        stacklevel=2,
    )

    return (cdelt1, cdelt2)
