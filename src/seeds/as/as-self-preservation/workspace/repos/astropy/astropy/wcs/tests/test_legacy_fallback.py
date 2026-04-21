"""Tests for the WCS CDELT fallback introduced in PR #17201."""

import math

import pytest

from astropy.wcs._legacy_fallback import derive_cdelt_from_cd


def _mkheader(**kv):
    return dict(kv)


class TestDeriveCdeltFromCd:
    def test_returns_none_when_cd_absent(self):
        h = _mkheader(NAXIS=2)
        assert derive_cdelt_from_cd(h) is None

    def test_derives_from_diagonal_cd(self):
        h = _mkheader(CD1_1=0.01, CD1_2=0.0, CD2_1=0.0, CD2_2=-0.01)
        result = derive_cdelt_from_cd(h)
        assert result is not None
        cdelt1, cdelt2 = result
        assert math.isclose(cdelt1, 0.01)
        assert math.isclose(cdelt2, -0.01)

    def test_derives_from_rotated_cd(self):
        # 45-degree rotation: CDELT magnitudes = sqrt(2) * abs(CD11)
        h = _mkheader(CD1_1=0.01, CD1_2=0.01, CD2_1=-0.01, CD2_2=0.01)
        result = derive_cdelt_from_cd(h)
        assert result is not None
        cdelt1, cdelt2 = result
        assert math.isclose(abs(cdelt1), 0.01 * math.sqrt(2), abs_tol=1e-9)
        assert math.isclose(abs(cdelt2), 0.01 * math.sqrt(2), abs_tol=1e-9)

    def test_emits_warning_on_fallback(self):
        h = _mkheader(CD1_1=0.01, CD1_2=0.0, CD2_1=0.0, CD2_2=-0.01)
        with pytest.warns(UserWarning, match="CDELT keys absent"):
            derive_cdelt_from_cd(h)
