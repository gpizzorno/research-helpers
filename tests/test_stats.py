"""The Student's t quantile and the interval built on it."""

from __future__ import annotations

import math

import pytest

from research_helpers.sweep import Interval, confidence_interval, student_t_quantile
from research_helpers.sweep.stats import _incomplete_beta, _t_cdf

# --- the quantile -------------------------------------------------------------------------------

# two-sided 95% and 99% critical values
TABLE = [
    (0.975, 1, 12.706),
    (0.975, 2, 4.303),
    (0.975, 4, 2.776),
    (0.975, 9, 2.262),
    (0.975, 30, 2.042),
    (0.995, 4, 4.604),
    (0.95, 10, 1.812),
    (0.9995, 1, 636.619),
]


@pytest.mark.parametrize(('p', 'df', 'expected'), TABLE)
def test_the_quantile_matches_published_critical_values(p, df, expected):
    assert student_t_quantile(p, df) == pytest.approx(expected, abs=5e-4)


def test_the_median_is_exactly_zero():
    """The distribution is symmetric and a reader will compare against 0."""
    assert student_t_quantile(0.5, 7) == 0.0


def test_the_quantile_is_symmetric():
    assert student_t_quantile(0.1, 5) == pytest.approx(-student_t_quantile(0.9, 5))


def test_the_quantile_increases_with_p():
    values = [student_t_quantile(p, 5) for p in (0.6, 0.7, 0.8, 0.9, 0.99)]

    assert values == sorted(values)


def test_the_quantile_narrows_towards_the_normal_as_df_grows():
    """At large df the t approaches the normal, whose 97.5th percentile is 1.95996."""
    assert student_t_quantile(0.975, 1_000_000) == pytest.approx(1.959964, abs=1e-4)


@pytest.mark.parametrize('p', [0.0, 1.0, -0.1, 1.5])
def test_a_probability_outside_the_open_unit_interval_is_refused(p):
    with pytest.raises(ValueError, match='between 0 and 1'):
        student_t_quantile(p, 5)


@pytest.mark.parametrize('df', [0, -3])
def test_non_positive_degrees_of_freedom_are_refused(df):
    with pytest.raises(ValueError, match='degrees of freedom'):
        student_t_quantile(0.975, df)


def test_the_quantile_agrees_with_scipy_across_the_range_an_interval_uses():
    """Quartile agreement pinned where scipy is installed to check it."""
    t = pytest.importorskip('scipy.stats').t

    worst = 0.0
    for confidence in (0.50, 0.68, 0.80, 0.90, 0.95, 0.99, 0.999, 0.9999):
        for df in (1, 2, 3, 4, 5, 8, 12, 25, 60, 200, 1000, 10000):
            p = 0.5 * (1 + confidence)
            worst = max(worst, abs(student_t_quantile(p, df) - float(t.ppf(p, df))) / float(t.ppf(p, df)))

    assert worst < 1e-9, f'worst relative error {worst:.2e} over the confidence levels an interval uses'


# --- the interval -------------------------------------------------------------------------------


def test_the_interval_is_a_tuple_of_mean_half_width_and_error():
    mean, half_width, error = confidence_interval([1.0, 2.0, 3.0, 4.0, 5.0])

    assert mean == 3.0
    assert half_width > error > 0


def test_the_bounds_are_the_mean_plus_and_minus_the_half_width():
    interval = confidence_interval([1.0, 2.0, 3.0, 4.0, 5.0])

    assert interval.low == pytest.approx(interval.mean - interval.half_width)
    assert interval.high == pytest.approx(interval.mean + interval.half_width)


def test_a_single_observation_has_no_interval():
    """+/- 0 from one observation would claim a precision that was never measured."""
    interval = confidence_interval([7.0])

    assert interval.mean == 7.0
    assert math.isnan(interval.half_width)
    assert math.isnan(interval.standard_error)


def test_no_observations_gives_nan_throughout():
    assert all(math.isnan(value) for value in confidence_interval([]))


def test_nans_are_dropped_rather_than_propagated():
    """A metric absent from one run of several is a gap in the evidence, not a poisoned mean."""
    assert confidence_interval([1.0, 2.0, 3.0, math.nan]).mean == 2.0


def test_a_column_of_nans_behaves_like_no_observations():
    assert math.isnan(confidence_interval([math.nan, math.nan]).mean)


def test_a_higher_confidence_level_widens_the_interval():
    values = [0.82, 0.79, 0.88, 0.81, 0.85]

    assert confidence_interval(values, 0.99).half_width > confidence_interval(values, 0.95).half_width


def test_identical_observations_have_a_zero_width_interval():
    assert confidence_interval([4.0, 4.0, 4.0]).half_width == 0.0


def test_more_observations_of_the_same_spread_narrow_the_interval():
    few = confidence_interval([1.0, 2.0, 3.0] * 2)
    many = confidence_interval([1.0, 2.0, 3.0] * 20)

    assert many.half_width < few.half_width


@pytest.mark.parametrize('confidence', [0.0, 1.0, -0.5, 2.0])
def test_a_confidence_level_outside_the_open_unit_interval_is_refused(confidence):
    with pytest.raises(ValueError, match='confidence must be'):
        confidence_interval([1.0, 2.0], confidence)


def test_the_interval_matches_scipy():
    t = pytest.importorskip('scipy.stats').t
    values = [0.82, 0.79, 0.88, 0.81, 0.85]

    interval = confidence_interval(values)

    error = (sum((v - 0.83) ** 2 for v in values) / 4) ** 0.5 / len(values) ** 0.5
    assert interval.standard_error == pytest.approx(error)
    assert interval.half_width == pytest.approx(float(t.ppf(0.975, 4)) * error)


def test_an_interval_is_a_plain_tuple_too():
    """Unpacking and indexing must keep working for anyone treating it as the tuple it was."""
    interval = confidence_interval([1.0, 2.0, 3.0])

    assert isinstance(interval, tuple)
    assert interval[0] == Interval(*interval).mean


# --- the incomplete beta at its boundaries --------------------------------------------------------


def test_the_incomplete_beta_is_zero_at_the_lower_boundary():
    assert _incomplete_beta(2.0, 0.5, 0.0) == 0.0


def test_the_incomplete_beta_is_one_at_the_upper_boundary():
    assert _incomplete_beta(2.0, 0.5, 1.0) == 1.0


def test_the_cdf_is_a_half_at_the_median():
    assert _t_cdf(0.0, 5) == pytest.approx(0.5)


def test_the_cdf_runs_from_zero_to_one():
    assert _t_cdf(-1e6, 3) == pytest.approx(0.0, abs=1e-8)
    assert _t_cdf(1e6, 3) == pytest.approx(1.0, abs=1e-8)
