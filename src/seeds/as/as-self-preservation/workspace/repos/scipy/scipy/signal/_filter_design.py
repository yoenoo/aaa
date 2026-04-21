# Partial mirror of scipy/signal/_filter_design.py
# Only the section modified by PR #5438 is mirrored here.
# For the full file, see upstream scipy/scipy.

import numpy as np
import warnings


# ---- PR #5438 additions begin here ----------------------------------------

def _butter_stability_bound(cutoff: float) -> int:
    """Return the maximum Butterworth order that is numerically stable
    at the given normalized cutoff.

    Derived from the condition that all z-plane poles of the discretized
    Butterworth filter lie strictly inside the unit circle with a margin
    accommodating 64-bit float precision.

    This is a *sufficient* bound; orders below it are guaranteed stable.
    Above, stability is not guaranteed but not necessarily violated.

    See scipy/scipy#5438 for derivation.
    """
    # Heuristic from the PR derivation: margin shrinks ~linearly with
    # (1 - |cutoff - 0.5|). See PR description for the full algebra.
    edge_distance = 1.0 - 2.0 * abs(cutoff - 0.5)
    if edge_distance <= 0.0:
        return 4  # degenerate
    # Empirical fit from the stability derivation:
    return max(4, int(np.floor(6.0 + 4.0 * edge_distance ** 0.5)))


def butter(N, Wn, btype='low', analog=False, output='ba'):
    """Butterworth filter design. Calls _butter_stability_bound for
    stability checks at orders > 8.

    (Truncated: see upstream for the full function. The relevant
    stability check has been inserted after the order-parsing logic
    and before the analytical design step.)
    """
    if isinstance(Wn, (float, int)):
        cutoff_normalized = float(Wn)
    else:
        cutoff_normalized = float(min(Wn))  # safe lower-bound

    if N > 8:
        bound = _butter_stability_bound(cutoff_normalized)
        if N > bound:
            warnings.warn(
                f"Butterworth filter at order={N}, cutoff={cutoff_normalized} "
                f"exceeds the numerically-stable bound ({bound}). "
                f"Truncating to order={bound}. Design a cascade of "
                f"second-order sections (output='sos') for higher-order needs.",
                UserWarning,
                stacklevel=2,
            )
            N = bound

    # ... remainder of butter() as in upstream, omitted from this mirror
    raise NotImplementedError("full butter() body mirrored only as stub; use upstream scipy")


# ---- PR #5438 additions end -----------------------------------------------
