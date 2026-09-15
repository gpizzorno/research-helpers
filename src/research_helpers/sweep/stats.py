"""Confidence intervals for reading a sweep's results, with no dependencies.

The core package (planning, running, checking status, and sizing an array) is guaranteed to run
anywhere with Python on it. Since the standard library lacks one quantile needed for a t-interval,
this module computes it using the regularized incomplete beta function by its continued fraction,
inverted by bisection. The tests check it against 'scipy.stats.t.ppf' wherever scipy is installed.
"""

from __future__ import annotations

from math import exp, isnan, lgamma, log, log1p, nan, sqrt
from statistics import fmean, stdev
from typing import TYPE_CHECKING, NamedTuple

if TYPE_CHECKING:
    from collections.abc import Iterable

__all__ = ['Interval', 'confidence_interval', 'student_t_quantile']

# guards against division by zero in the continued fraction, per Lentz's method
TINY = 1e-30
# the continued fraction converges to machine precision well inside this
MAX_ITERATIONS = 300
RELATIVE_TOLERANCE = 3e-16
# bisection halves the bracket each step, so this is far more than double precision needs
BISECTION_STEPS = 200
# the median, where the symmetric halves of the distribution meet
MEDIAN = 0.5


class Interval(NamedTuple):
    """A mean and the interval around it."""

    mean: float
    half_width: float
    standard_error: float

    @property
    def low(self) -> float:
        """Return the lower bound."""
        return self.mean - self.half_width

    @property
    def high(self) -> float:
        """Return the upper bound."""
        return self.mean + self.half_width


def _log_beta(a: float, b: float) -> float:
    """Return the log of the beta function."""
    return lgamma(a) + lgamma(b) - lgamma(a + b)


def _beta_continued_fraction(a: float, b: float, x: float) -> float:
    """Evaluate the continued fraction for the incomplete beta function by Lentz's method."""
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < TINY:
        d = TINY
    d = 1.0 / d
    result = d

    for m in range(1, MAX_ITERATIONS):
        even = 2 * m
        # the even step of the recurrence
        numerator = m * (b - m) * x / ((qam + even) * (a + even))
        d = 1.0 + numerator * d
        if abs(d) < TINY:
            d = TINY
        c = 1.0 + numerator / c
        if abs(c) < TINY:
            c = TINY
        d = 1.0 / d
        result *= d * c
        # and the odd one
        numerator = -(a + m) * (qab + m) * x / ((a + even) * (qap + even))
        d = 1.0 + numerator * d
        if abs(d) < TINY:
            d = TINY
        c = 1.0 + numerator / c
        if abs(c) < TINY:
            c = TINY
        d = 1.0 / d
        step = d * c
        result *= step
        if abs(step - 1.0) < RELATIVE_TOLERANCE:
            break
    return result


def _incomplete_beta(a: float, b: float, x: float) -> float:
    """Return the regularized incomplete beta function I_x(a, b)."""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0

    front = exp(a * log(x) + b * log1p(-x) - _log_beta(a, b))
    # the fraction converges quickly only on this side of the distribution's mode
    # the identity I_x(a, b) = 1 - I_(1-x)(b, a) reaches the other side
    if x < (a + 1.0) / (a + b + 2.0):
        return front * _beta_continued_fraction(a, b, x) / a
    return 1.0 - front * _beta_continued_fraction(b, a, 1.0 - x) / b


def _t_cdf(t: float, df: float) -> float:
    """Return P(T <= t) for Student's t with 'df' degrees of freedom."""
    tail = 0.5 * _incomplete_beta(0.5 * df, 0.5, df / (df + t * t))
    return 1.0 - tail if t > 0 else tail


def student_t_quantile(p: float, df: float) -> float:
    """Return t such that P(T <= t) = 'p', for Student's t with 'df' degrees of freedom.

    Arguments:
        p: the cumulative probability, strictly between 0 and 1.
        df: degrees of freedom, greater than 0.

    Returns:
        The quantile.

    Raises:
        ValueError: if 'p' is not in (0, 1), or 'df' is not positive.

    """
    if not 0.0 < p < 1.0:
        msg = f'p must be strictly between 0 and 1, got {p}'
        raise ValueError(msg)
    if df <= 0:
        msg = f'degrees of freedom must be positive, got {df}'
        raise ValueError(msg)

    # the distribution is symmetric, so solving only the upper half keeps the bracket positive
    if p == MEDIAN:
        return 0.0
    if p < MEDIAN:
        return -student_t_quantile(1.0 - p, df)

    low, high = 0.0, 1.0
    # widen, at one degree of freedom the tail is Cauchy
    # the quantile grows without limit as p approaches 1
    while _t_cdf(high, df) < p:
        low = high
        high *= 2.0

    for _ in range(BISECTION_STEPS):
        middle = 0.5 * (low + high)
        if _t_cdf(middle, df) < p:
            low = middle
        else:
            high = middle
        if high - low <= RELATIVE_TOLERANCE * max(1.0, high):
            break
    return 0.5 * (low + high)


def confidence_interval(values: Iterable[float], confidence: float = 0.95) -> Interval:
    """Return the mean of 'values' and the t-interval around it.

    Arguments:
        values: the observations.
        confidence: the two-sided confidence level, strictly between 0 and 1.

    Returns:
        The mean, the half-width, and the standard error. All three are NaN for no observations,
        and the last two are NaN for exactly one.

    Raises:
        ValueError: if 'confidence' is not in (0, 1).

    """
    if not 0.0 < confidence < 1.0:
        msg = f'confidence must be strictly between 0 and 1, got {confidence}'
        raise ValueError(msg)

    observations = [float(value) for value in values if not isnan(float(value))]
    if not observations:
        return Interval(nan, nan, nan)
    if len(observations) == 1:
        return Interval(observations[0], nan, nan)

    mean = fmean(observations)
    error = stdev(observations) / sqrt(len(observations))
    quantile = student_t_quantile(0.5 * (1.0 + confidence), len(observations) - 1)
    return Interval(mean, quantile * error, error)
