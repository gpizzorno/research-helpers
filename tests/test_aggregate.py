"""Combining several runs of one grid into a table with confidence intervals."""

from __future__ import annotations

import math

import pytest

from research_helpers.project import _load
from research_helpers.sweep import Sweep, aggregate_runs, read_parts, run_slice

pytest.importorskip('pandas')

GRID = {'alpha': [0.1, 0.2], 'beta': [1, 2, 3]}


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path):
    monkeypatch.delenv('RESEARCH_HELPERS_ROOT', raising=False)
    _load.cache_clear()
    workdir = tmp_path / 'nowhere'
    workdir.mkdir()
    monkeypatch.chdir(workdir)
    yield
    _load.cache_clear()


def make_run(tmp_path, name, offset, *, extra=None):
    """Plan and run one whole sweep, scoring each combination with a per-run offset."""

    def score(params, _context):
        measured = {'objective': params['alpha'] * params['beta'] + offset}
        if extra:
            measured.update(extra)
        return measured

    run_dir = tmp_path / name
    sweep = Sweep(evaluate=score)
    sweep.plan(run_dir, GRID, constants={'dataset': name}, n_tasks=1)
    run_slice(run_dir, sweep.evaluation, task_index=1, quiet=True)
    return run_dir


@pytest.fixture
def three_runs(tmp_path):
    """Return three runs of the same grid, differing by a constant offset."""
    return [make_run(tmp_path, f'run{i}', offset) for i, offset in enumerate((0.0, 0.1, 0.2))]


def test_one_row_per_parameter_setting(three_runs):
    frame = aggregate_runs(three_runs)

    assert len(frame) == 6, 'the grid has six settings, however many runs covered it'


def test_the_grouping_defaults_to_the_swept_parameters(three_runs):
    frame = aggregate_runs(three_runs)

    assert {'alpha', 'beta'} <= set(frame.columns)
    assert 'combination_id' not in frame.columns


def test_every_setting_is_seen_in_every_run(three_runs):
    frame = aggregate_runs(three_runs)

    assert set(frame['n_runs']) == {3}


def test_the_mean_is_taken_across_runs(three_runs):
    frame = aggregate_runs(three_runs)
    row = frame[(frame['alpha'] == 0.1) & (frame['beta'] == 2)].iloc[0]

    # 0.2 + each run's offset of 0.0, 0.1, 0.2
    assert row['objective_mean'] == pytest.approx(0.3)


def test_an_interval_and_a_standard_error_come_with_each_metric(three_runs):
    frame = aggregate_runs(three_runs)

    assert {'objective_mean', 'objective_ci', 'objective_sem'} <= set(frame.columns)
    assert (frame['objective_ci'] > 0).all()


def test_a_single_run_reports_no_interval(tmp_path):
    """Aggregating one run must not imply a precision that one draw cannot support."""
    frame = aggregate_runs([make_run(tmp_path, 'only', 0.0)])

    assert set(frame['n_runs']) == {1}
    assert frame['objective_ci'].isna().all()


def test_a_higher_confidence_level_widens_the_intervals(three_runs):
    wide = aggregate_runs(three_runs, confidence=0.99)['objective_ci']
    narrow = aggregate_runs(three_runs, confidence=0.95)['objective_ci']

    assert (wide > narrow).all()


def test_grouping_by_combination_id_is_refused(three_runs):
    """The id hashes the constants, so it silently yields one observation per group."""
    with pytest.raises(ValueError, match=r'not .combination_id.'):
        aggregate_runs(three_runs, group_by=['combination_id', 'alpha'])


def test_the_ids_really_do_differ_across_runs(three_runs):
    """Pinning the fact the refusal above exists to protect against."""
    ids = [{record['combination_id'] for record in read_parts(run)} for run in three_runs]

    assert ids[0].isdisjoint(ids[1]), 'different constants, so different ids for the same setting'


def test_an_explicit_grouping_is_honoured(three_runs):
    frame = aggregate_runs(three_runs, group_by=['alpha'])

    assert len(frame) == 2


def test_metrics_can_be_named(three_runs):
    frame = aggregate_runs(three_runs, metrics=['objective'])

    assert 'runtime_seconds_mean' not in frame.columns


def test_a_metric_missing_from_one_run_still_aggregates_over_the_others(tmp_path):
    """A measurement added part-way through a series should not void the whole row."""
    runs = [
        make_run(tmp_path, 'early', 0.0),
        make_run(tmp_path, 'later', 0.1, extra={'recall': 0.5}),
        make_run(tmp_path, 'latest', 0.2, extra={'recall': 0.7}),
    ]

    frame = aggregate_runs(runs)

    assert frame['recall_mean'].iloc[0] == pytest.approx(0.6)
    assert not math.isnan(frame['objective_mean'].iloc[0])


def test_engine_bookkeeping_is_not_aggregated_as_a_measurement(three_runs):
    frame = aggregate_runs(three_runs)

    assert 'task_index_mean' not in frame.columns


def test_no_run_directories_is_an_error():
    with pytest.raises(ValueError, match='no run directories'):
        aggregate_runs([])


def test_runs_that_share_no_such_column_say_so(three_runs):
    with pytest.raises(ValueError, match='may not share a grid'):
        aggregate_runs(three_runs, group_by=['gamma'])


def test_run_directories_with_no_results_yet_say_so(tmp_path):
    """Planned but never run: an empty table would look like a finished experiment with no signal."""
    run_dir = tmp_path / 'planned'
    Sweep(evaluate=lambda p, _c: {'objective': p['alpha']}).plan(run_dir, GRID, n_tasks=1)
    (run_dir / 'parts').mkdir()

    with pytest.raises(ValueError, match='hold any results yet'):
        aggregate_runs([run_dir])
