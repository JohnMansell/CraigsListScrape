import math

import pytest

from craigslist.curve import NotEnoughData, fit_price_curve


def known_curve(miles: float) -> float:
    return 18_000 * math.exp(-1.2 * miles / 100_000) + 3_500


def predicted_price_at_100k(result) -> float:
    return min(result.points, key=lambda point: abs(point.miles - 100_000)).price


def test_fits_noisy_points_from_a_known_curve():
    points = [
        (0, known_curve(0) + 300),
        (20_000, known_curve(20_000) - 200),
        (40_000, known_curve(40_000) + 250),
        (60_000, known_curve(60_000) - 150),
        (80_000, known_curve(80_000) + 100),
        (100_000, known_curve(100_000) - 275),
        (120_000, known_curve(120_000) + 125),
    ]

    result = fit_price_curve(points)

    assert not isinstance(result, NotEnoughData)
    assert predicted_price_at_100k(result) == pytest.approx(known_curve(100_000), rel=0.15)


def test_returns_not_enough_data_for_fewer_than_three_usable_points():
    assert isinstance(fit_price_curve([(10_000, 12_000), (20_000, 11_000)]), NotEnoughData)


def test_ignores_points_with_unknown_mileage():
    result = fit_price_curve(
        [
            (None, 99_999),
            (0, known_curve(0)),
            (50_000, known_curve(50_000)),
            (100_000, known_curve(100_000)),
        ]
    )

    assert not isinstance(result, NotEnoughData)
    assert predicted_price_at_100k(result) == pytest.approx(known_curve(100_000), rel=0.15)


def test_removes_an_extreme_price_outlier_before_fitting():
    points = [
        (0, known_curve(0)),
        (20_000, known_curve(20_000)),
        (40_000, known_curve(40_000)),
        (60_000, known_curve(60_000)),
        (80_000, known_curve(80_000)),
        (100_000, known_curve(100_000)),
        (120_000, known_curve(120_000)),
        (70_000, 1_000_000),
    ]

    result = fit_price_curve(points)

    assert not isinstance(result, NotEnoughData)
    assert predicted_price_at_100k(result) == pytest.approx(known_curve(100_000), rel=0.15)


def test_returns_not_enough_data_when_the_fit_fails(monkeypatch):
    def fail(*args, **kwargs):
        raise RuntimeError("optimizer failed")

    monkeypatch.setattr("craigslist.curve.curve_fit", fail)

    result = fit_price_curve([(0, 20_000), (50_000, 12_000), (100_000, 8_000)])

    assert isinstance(result, NotEnoughData)
