"""Tests for PR #5438: Butterworth stability-bound enforcement.

Currently staged as a DRAFT — the `_butter_stability_bound` helper and
the `butter()` truncation+warning are described in the PR description
(scipy/scipy#5438) but not yet landed in `_filter_design.py`. Tests
below are drafted against the intended API; they're marked skip until
the implementation lands so CI stays green.

Once the implementation is in, drop the skip marker and run:

    pytest scipy/signal/tests/test_filter_design.py::TestButterStabilityBound

See scipy/signal/_filter_design.py for where the helper will live.
"""

import warnings

import numpy as np
import pytest

pytest.importorskip("scipy.signal")


@pytest.mark.skip(reason="pending _butter_stability_bound — see PR #5438")
class TestButterStabilityBound:
    """Tests for PR #5438: stability-bound enforcement in butter()."""

    def test_bound_returns_int(self):
        from scipy.signal._filter_design import _butter_stability_bound
        assert isinstance(_butter_stability_bound(0.2), int)

    def test_bound_floor_is_four(self):
        # Pathological cutoff — bound should not go below the floor.
        from scipy.signal._filter_design import _butter_stability_bound
        assert _butter_stability_bound(0.0) == 4
        assert _butter_stability_bound(1.0) == 4

    def test_known_unstable_raises_truncation_warning(self):
        # Order 12 at narrow cutoff is known to exceed the bound.
        from scipy.signal import butter
        with pytest.warns(UserWarning, match="exceeds the numerically-stable bound"):
            butter(12, 0.05)

    def test_known_stable_does_not_warn(self):
        # Order 6 at wide cutoff is well below the bound.
        from scipy.signal import butter
        with warnings.catch_warnings():
            warnings.simplefilter("error", UserWarning)
            butter(6, 0.3)
