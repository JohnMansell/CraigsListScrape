"""Fit price-versus-mileage curves without depending on a charting library."""
from collections.abc import Iterable
from dataclasses import dataclass
import warnings

import numpy as np
from scipy.optimize import OptimizeWarning, curve_fit  # type: ignore[import-untyped]

MILE_SCALE = 100_000
SAMPLE_COUNT = 101

MileagePrice = tuple[int | None, float]


@dataclass(frozen=True)
class CurvePoint:
    """One sampled point on a fitted price curve."""

    miles: float
    price: float


@dataclass(frozen=True)
class PriceCurve:
    """Sampled points ready for a caller to draw."""

    points: tuple[CurvePoint, ...]


@dataclass(frozen=True)
class NotEnoughData:
    """A curve could not be fitted from the available points."""

    reason: str


def fit_price_curve(points: Iterable[MileagePrice]) -> PriceCurve | NotEnoughData:
    """Fit ``price = a * exp(-b * miles) + c`` and sample it for drawing.

    Unknown mileage and price outliers are excluded before fitting. A failed or
    underdetermined fit is returned as ``NotEnoughData`` instead of raising.
    """
    usable = [(miles, price) for miles, price in points if miles is not None]
    if len(usable) < 3:
        return NotEnoughData("fewer than three points have known mileage")

    miles = np.asarray([point[0] for point in usable], dtype=float)
    prices = np.asarray([point[1] for point in usable], dtype=float)
    finite = np.isfinite(miles) & np.isfinite(prices)
    miles, prices = miles[finite], prices[finite]
    if len(miles) < 3:
        return NotEnoughData("fewer than three points are finite")
    if np.any(prices <= 0):
        return NotEnoughData("prices must be positive")

    inliers = _price_inliers(prices)
    miles, prices = miles[inliers], prices[inliers]
    if len(miles) < 3:
        return NotEnoughData("fewer than three points remain after outlier removal")

    scaled_miles = miles / MILE_SCALE
    initial = _initial_guess(prices, scaled_miles)
    try:
        with warnings.catch_warnings():
            # Three points determine the three parameters but leave no degrees
            # of freedom to estimate covariance. The curve is still usable.
            warnings.simplefilter("ignore", OptimizeWarning)
            parameters, _ = curve_fit(
                _decay,
                scaled_miles,
                prices,
                p0=initial,
                bounds=([0, 0, 0], [np.inf, np.inf, np.inf]),
                maxfev=10_000,
            )
    except (FloatingPointError, RuntimeError, ValueError, OptimizeWarning):
        return NotEnoughData("curve fitting failed")

    sample_miles = np.linspace(miles.min(), miles.max(), SAMPLE_COUNT)
    sample_prices = _decay(sample_miles / MILE_SCALE, *parameters)
    if not np.all(np.isfinite(sample_prices)):
        return NotEnoughData("curve fitting produced non-finite prices")
    return PriceCurve(tuple(CurvePoint(float(mileage), float(price)) for mileage, price in zip(sample_miles, sample_prices)))


def _decay(miles: np.ndarray, amplitude: float, rate: float, floor: float) -> np.ndarray:
    return amplitude * np.exp(-rate * miles) + floor


def _price_inliers(prices: np.ndarray) -> np.ndarray:
    first_quartile, third_quartile = np.percentile(prices, [25, 75])
    spread = third_quartile - first_quartile
    return (prices >= first_quartile - 1.5 * spread) & (prices <= third_quartile + 1.5 * spread)


def _initial_guess(prices: np.ndarray, miles: np.ndarray) -> tuple[float, float, float]:
    floor = max(0.0, float(2 * prices.min() - prices.max()))
    amplitude = float(prices.max() - floor)
    slope, _ = np.polyfit(miles, np.log(prices - floor), 1)
    return amplitude, max(0.01, float(-slope)), floor
