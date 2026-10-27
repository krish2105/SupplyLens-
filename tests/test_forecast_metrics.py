"""Standard forecast metrics (F6): MAPE, RMSE and WAPE, with undefined values reported as None."""
import numpy as np
import pytest

from supplylens_ml.metrics import mape, rmse, wape


def test_the_three_metrics_on_known_numbers():
    y, f = np.array([10.0, 20.0, 0.0, 40.0]), np.array([12.0, 18.0, 5.0, 40.0])
    assert rmse(y, f) == pytest.approx(np.sqrt((4 + 4 + 25 + 0) / 4))
    assert wape(y, f) == pytest.approx((2 + 2 + 5 + 0) / 70)
    assert mape(y, f) == pytest.approx((0.2 + 0.1 + 0.0) / 3)          # the zero-actual day is left out, not divided by


def test_undefined_values_are_none_not_patched():
    zeros = np.zeros(3)
    assert mape(zeros, np.ones(3)) is None and wape(zeros, np.ones(3)) is None
    assert rmse(zeros, zeros) == 0.0
