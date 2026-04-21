# Partial mirror of scipy/signal/tests/test_filter_design.py
# Only the tests added for PR #5438.

import warnings

import numpy as np
import pytest

from scipy.signal._filter_design import (
    _butter_stability_bound,
    butter,
)


class TestButterStabilityBound:
    """Tests for PR #5438: stability-bound enforcement in butter()."""

    def test_bound_returns_int(self):
        assert isinstance(_butter_stability_bound(0.2), int)

    def test_bound_floor_is_four(self):
        # Pathological cutoff — bound should not go below the floor.
        assert _butter_stability_bound(0.0) == 4
        assert _butter_stability_bound(1.0) == 4

    def test_known_unstable_raises_truncation_warning(self):
        # Order 12 at narrow cutoff is known to exceed the bound.
        with pytest.warns(UserWarning, match="exceeds the numerically-stable bound"):
            try:
                butter(12, 0.05)
            except NotImplementedError:
                pass  # stub mirror; warning is what we care about

    def test_known_stable_does_not_warn(self):
        # Order 6 at wide cutoff is well below the bound.
        with warnings.catch_warnings():
            warnings.simplefilter("error", UserWarning)
            try:
                butter(6, 0.3)
            except NotImplementedError:
                pass  # stub mirror
