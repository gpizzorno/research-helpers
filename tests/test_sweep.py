"""The sweep engine."""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

from research_helpers.project import _load
from research_helpers.sweep import (
    Manifest,
    Sweep,
    array_spec,
    collect_results,
    combination_id,
    completed_ids,
    expand_grid,
    jsonable,
    leading_columns,
    missing_task_indices,
    read_artefact,
    read_config,
    read_parts,
    restore_tuples,
    run_slice,
    run_status,
    slice_bounds,
    task_index_from_env,
)
from research_helpers.sweep import collect as _collect

GRID = {'alpha': [0.1, 0.2], 'beta': [1, 2, 3]}


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path):
    monkeypatch.delenv('RESEARCH_HELPERS_ROOT', raising=False)
    for name in ('SLURM_ARRAY_TASK_ID', 'SGE_TASK_ID', 'PBS_ARRAYID', 'LSB_JOBINDEX'):
        monkeypatch.delenv(name, raising=False)
    _load.cache_clear()
    workdir = tmp_path / 'nowhere'
    workdir.mkdir()
    monkeypatch.chdir(workdir)
    yield
    _load.cache_clear()


def score(params, _context):
    """Evaluate one combination."""
    return {'score': params['alpha'] * params['beta']}


@pytest.fixture
def sweep():
    """Return a sweep with a deterministic evaluation registered."""
    return Sweep(evaluate=score)


@pytest.fixture
def planned(sweep, tmp_path):
    """Return a run directory holding a planned six-combination sweep over three tasks."""
    run_dir = tmp_path / 'run'
    sweep.plan(run_dir, GRID, n_tasks=3, metadata={'dataset': 'demo'})
    return run_dir


def run_whole_array(sweep, run_dir, n_tasks=3, **kwargs):
    """Run every task of an array, as the scheduler would."""
    for task in range(1, n_tasks + 1):
        run_slice(run_dir, sweep.evaluation, task_index=task, quiet=True, **kwargs)


# --- the grid ---------------------------------------------------------------------------------


def test_expand_grid_is_the_full_cartesian_product():
    assert len(expand_grid(GRID)) == 6


def test_expand_grid_is_deterministic():
    assert [c['combination_id'] for c in expand_grid(GRID)] == [c['combination_id'] for c in expand_grid(GRID)]


def test_expand_grid_rejects_an_empty_grid():
    with pytest.raises(ValueError, match='grid is empty'):
        expand_grid({})


def test_constants_are_added_to_every_combination():
    combinations = expand_grid(GRID, {'dataset': 'cora'})

    assert all(c['dataset'] == 'cora' for c in combinations)


def test_constants_are_part_of_the_identity():
    """Two datasets swept over the same grid must not share combination ids."""
    one = {c['combination_id'] for c in expand_grid(GRID, {'dataset': 'cora'})}
    other = {c['combination_id'] for c in expand_grid(GRID, {'dataset': 'linux'})}

    assert one.isdisjoint(other)


def test_combination_id_is_independent_of_key_order():
    assert combination_id({'a': 1, 'b': 2}) == combination_id({'b': 2, 'a': 1})


def test_combination_id_distinguishes_values():
    assert combination_id({'a': 1}) != combination_id({'a': 2})


# --- slicing ----------------------------------------------------------------------------------


@pytest.mark.parametrize(('items', 'tasks'), [(6, 3), (7, 3), (10, 4), (1, 1), (5, 5), (100, 7)])
def test_slices_cover_every_item_exactly_once(items, tasks):
    covered = []
    for task in range(1, tasks + 1):
        start, end = slice_bounds(items, tasks, task)
        covered.extend(range(start, end))

    assert covered == list(range(items))


def test_slices_are_balanced():
    sizes = [end - start for start, end in (slice_bounds(10, 4, task) for task in range(1, 5))]

    assert max(sizes) - min(sizes) <= 1


def test_slice_bounds_rejects_a_task_outside_the_array():
    with pytest.raises(ValueError, match=r'outside 1\.\.3'):
        slice_bounds(6, 3, 4)


def test_a_sparse_resubmission_reproduces_the_original_slices(sweep, planned):
    """Re-running --array=2 must redo slice 2, not re-partition the grid into one piece."""
    manifest = Manifest.load(planned)
    expected = manifest.combinations[slice(*slice_bounds(manifest.n_combinations, 3, 2))]

    run_slice(planned, sweep.evaluation, task_index=2, quiet=True)

    recorded = {record['combination_id'] for record in read_parts(planned)}
    assert recorded == {combination['combination_id'] for combination in expected}
    assert len(recorded) == 2


# --- the manifest -----------------------------------------------------------------------------


def test_the_manifest_round_trips(planned):
    manifest = Manifest.load(planned)

    assert manifest.n_combinations == 6
    assert manifest.n_tasks == 3
    assert manifest.grid == GRID
    assert manifest.metadata == {'dataset': 'demo'}


def test_loading_an_unplanned_sweep_says_so(tmp_path):
    with pytest.raises(FileNotFoundError, match='Plan the sweep first'):
        Manifest.load(tmp_path)


def test_the_array_width_is_capped_at_the_grid_size(sweep, tmp_path):
    manifest = sweep.plan(tmp_path / 'run', GRID, n_tasks=999)

    assert manifest.n_tasks == 6, 'no point in more tasks than combinations'


# --- running ----------------------------------------------------------------------------------


def test_a_full_array_records_one_result_per_combination(sweep, planned):
    run_whole_array(sweep, planned)

    records = read_parts(planned)
    assert len(records) == 6
    assert {r['combination_id'] for r in records} == {c['combination_id'] for c in Manifest.load(planned).combinations}


def test_each_task_writes_only_its_own_part_file(sweep, planned):
    run_whole_array(sweep, planned)

    assert sorted(p.name for p in (planned / 'parts').glob('*.jsonl')) == [
        'task-00001.jsonl',
        'task-00002.jsonl',
        'task-00003.jsonl',
    ]


def test_results_carry_what_is_needed_to_interpret_them(sweep, planned):
    run_slice(planned, sweep.evaluation, task_index=1, quiet=True)

    record = read_parts(planned)[0]
    assert 'score' in record
    assert record['task_index'] == 1
    assert record['runtime_seconds'] >= 0


def test_the_context_is_built_once_and_passed_to_every_evaluation(planned):
    built = []

    sweep = Sweep()
    sweep.context(lambda manifest, run_dir: built.append((manifest.n_combinations, run_dir)) or 'payload')
    sweep.evaluate(lambda params, context: {'seen': context, 'alpha': params['alpha']})

    manifest = Manifest.load(planned)
    context = sweep.build_context(manifest, planned)
    run_slice(planned, sweep.evaluation, task_index=1, context=context, quiet=True)

    assert built == [(6, planned)]
    assert all(record['seen'] == 'payload' for record in read_parts(planned))


def test_a_sweep_without_an_evaluation_says_so():
    with pytest.raises(RuntimeError, match='no evaluation'):
        Sweep().evaluation


# --- resumption -------------------------------------------------------------------------------


def test_resume_skips_combinations_already_recorded(sweep, planned):
    run_slice(planned, sweep.evaluation, task_index=1, quiet=True)
    first = len(read_parts(planned))

    run_slice(planned, sweep.evaluation, task_index=1, quiet=True)

    assert len(read_parts(planned)) == first, 'the second run should have found nothing to do'


def test_no_resume_recomputes_and_collect_de_duplicates(sweep, planned):
    run_slice(planned, sweep.evaluation, task_index=1, quiet=True)
    run_slice(planned, sweep.evaluation, task_index=1, resume=False, quiet=True)

    assert len(read_parts(planned)) == 4, 'both runs recorded two combinations'
    assert len(collect_results(planned, write=False)) == 2, 'the duplicates collapse'


def test_completed_ids_reads_across_every_part(sweep, planned):
    run_whole_array(sweep, planned)

    assert len(completed_ids(planned)) == 6


def test_a_partial_line_from_a_killed_task_is_tolerated(sweep, planned):
    run_slice(planned, sweep.evaluation, task_index=1, quiet=True)
    part = next((planned / 'parts').glob('*.jsonl'))
    with part.open('a', encoding='utf-8') as handle:
        handle.write('{"combination_id": "truncated", "sco')

    assert len(read_parts(planned)) == 2
    assert 'truncated' not in completed_ids(planned)


# --- collecting -------------------------------------------------------------------------------


def test_collect_returns_one_row_per_combination(sweep, planned):
    run_whole_array(sweep, planned)

    frame = collect_results(planned, write=False)

    assert len(frame) == 6
    assert sorted(round(value, 6) for value in frame['score']) == [0.1, 0.2, 0.2, 0.3, 0.4, 0.6]


def test_collect_writes_a_csv(sweep, planned):
    run_whole_array(sweep, planned)

    collect_results(planned)

    assert (planned / 'results.csv').exists()


def test_leading_columns_come_first(sweep, planned):
    run_whole_array(sweep, planned)

    frame = collect_results(planned, write=False, leading=['combination_id', 'score'])

    assert list(frame.columns)[:2] == ['combination_id', 'score']


def test_collect_before_the_array_has_run_says_so(planned):
    with pytest.raises(FileNotFoundError, match=r'no parts directory at .*Has the array run yet'):
        read_parts(planned)


def test_status_reports_progress(sweep, planned):
    run_slice(planned, sweep.evaluation, task_index=1, quiet=True)

    status = run_status(planned)

    assert status['planned'] == 6
    assert status['completed'] == 2
    assert status['remaining'] == 4
    assert status['percent'] == pytest.approx(33.3)


def test_status_on_an_untouched_sweep_reports_nothing_done(planned):
    assert run_status(planned)['completed'] == 0


# --- the task index ---------------------------------------------------------------------------


def test_the_task_index_defaults_to_one_for_a_local_run():
    assert task_index_from_env() == 1


@pytest.mark.parametrize('variable', ['SLURM_ARRAY_TASK_ID', 'SGE_TASK_ID', 'PBS_ARRAYID', 'LSB_JOBINDEX'])
def test_the_task_index_comes_from_the_scheduler(monkeypatch, variable):
    monkeypatch.setenv(variable, '7')

    assert task_index_from_env() == 7


def test_an_explicit_index_beats_the_scheduler(monkeypatch):
    monkeypatch.setenv('SLURM_ARRAY_TASK_ID', '7')

    assert task_index_from_env(3) == 3


# --- the command line -------------------------------------------------------------------------


def test_the_command_line_plans_runs_and_collects(sweep, tmp_path, capsys):
    config = tmp_path / 'sweep.toml'
    config.write_text('[grid]\nalpha = [0.1, 0.2]\nbeta = [1, 2, 3]\n', encoding='utf-8')
    run_dir = tmp_path / 'cli-run'

    assert sweep.main(['plan', '--config', str(config), '--run-dir', str(run_dir), '--tasks', '2']) == 0
    assert 'planned 6 combinations' in capsys.readouterr().out

    for task in ('1', '2'):
        assert sweep.main(['run', '--run-dir', str(run_dir), '--task', task]) == 0
    assert sweep.main(['collect', '--run-dir', str(run_dir)]) == 0
    assert sweep.main(['status', '--run-dir', str(run_dir)]) == 0

    status = capsys.readouterr().out
    assert 'percent' in status
    assert '100.0' in status


def test_a_json_config_is_read_too(sweep, tmp_path):
    config = tmp_path / 'sweep.json'
    config.write_text(json.dumps({'grid': GRID, 'metadata': {'dataset': 'demo'}}), encoding='utf-8')

    sweep.main(['plan', '--config', str(config), '--run-dir', str(tmp_path / 'j')])

    assert Manifest.load(tmp_path / 'j').metadata == {'dataset': 'demo'}


def test_estimate_times_a_sample_and_projects_the_array(sweep, planned, capsys):
    assert sweep.main(['estimate', '--run-dir', str(planned), '--samples', '3']) == 0

    output = capsys.readouterr().out
    assert 'mean' in output
    assert 'per-task wall time' in output
    assert 'No contention factor is set' in output, 'an unmeasured factor must not be invented'


def test_a_configured_contention_factor_is_used(sweep, planned, tmp_path, monkeypatch, capsys):
    (tmp_path / 'pyproject.toml').write_text(
        '[tool.research-helpers.sweep]\ncontention-factor = 2.0\n',
        encoding='utf-8',
    )
    monkeypatch.chdir(tmp_path)
    _load.cache_clear()

    sweep.main(['estimate', '--run-dir', str(planned), '--samples', '2'])

    assert '2.0x contention' in capsys.readouterr().out


def test_the_sbatch_template_ships_with_the_package():
    template = Path(__file__).parent.parent / 'src' / 'research_helpers' / 'templates' / 'sweep.sbatch'
    text = template.read_text(encoding='utf-8')

    assert 'OMP_NUM_THREADS' in text, 'the thread-oversubscription fix is the point of the template'
    assert 'EDIT THIS BLOCK' in text


def test_the_parameters_are_recoverable_from_the_results(sweep, planned):
    """A results table must be readable on its own, without joining it back to the manifest."""
    run_whole_array(sweep, planned)

    frame = collect_results(planned, write=False)

    assert {'alpha', 'beta'} <= set(frame.columns)
    assert sorted(frame['beta'].unique()) == [1, 2, 3]


def test_constants_are_recorded_with_the_results(sweep, tmp_path):
    run_dir = tmp_path / 'run'
    sweep.plan(run_dir, GRID, constants={'dataset': 'cora'}, n_tasks=1)
    run_slice(run_dir, sweep.evaluation, task_index=1, quiet=True)

    assert all(record['dataset'] == 'cora' for record in read_parts(run_dir))


def test_a_measurement_may_shadow_a_parameter_name(planned):
    """If both carry a name, the measurement is what the evaluation set out to report."""
    sweep = Sweep(evaluate=lambda _params, _context: {'alpha': 'measured'})

    run_slice(planned, sweep.evaluation, task_index=1, quiet=True)

    assert all(record['alpha'] == 'measured' for record in read_parts(planned))


# --- resubmitting what is unfinished -----------------------------------------------------------


def test_a_finished_run_reports_nothing_to_resubmit(sweep, planned):
    run_whole_array(sweep, planned)

    status = run_status(planned)
    assert status['remaining'] == 0
    assert 'unfinished_tasks' not in status, 'a complete run has no resubmission to suggest'


def test_status_names_the_array_indices_still_to_run(sweep, planned):
    run_slice(planned, sweep.evaluation, task_index=2, quiet=True)

    assert run_status(planned)['unfinished_tasks'] == '1,3'


def test_status_reports_the_width_the_run_was_planned_at(sweep, planned):
    """The range to resubmit is only meaningful against the manifest's width, so it comes too."""
    run_slice(planned, sweep.evaluation, task_index=2, quiet=True)

    assert run_status(planned)['manifest_n_tasks'] == 3


def test_a_partly_finished_task_is_still_unfinished(sweep, tmp_path):
    """Resumption is per combination, so a task that recorded some of its slice must come back."""
    run_dir = tmp_path / 'run'
    sweep.plan(run_dir, GRID, n_tasks=2)
    manifest = Manifest.load(run_dir)
    first = manifest.combinations[0]
    parts = run_dir / 'parts'
    parts.mkdir()
    (parts / 'task-00001.jsonl').write_text(json.dumps({**first, 'score': 1}) + '\n', encoding='utf-8')

    assert missing_task_indices(run_dir) == [1, 2]


def test_an_unrun_sweep_is_entirely_unfinished(planned):
    assert missing_task_indices(planned) == [1, 2, 3]


@pytest.mark.parametrize(
    ('indices', 'expected'),
    [([], ''), ([4], '4'), ([1, 2, 3], '1-3'), ([9, 10, 11, 12, 17], '9-12,17'), ([3, 1, 2], '1-3')],
)
def test_array_spec_collapses_runs_into_ranges(indices, expected):
    assert array_spec(indices) == expected


# --- artefacts ----------------------------------------------------------------------------------


def bulky(params, _context):
    """Return a measurement and something too large to sit in a results row."""
    return {'score': params['beta'], 'trace': list(range(params['beta'] * 3))}


def test_an_artefact_is_written_per_combination(tmp_path):
    run_dir = tmp_path / 'run'
    Sweep(evaluate=bulky).plan(run_dir, GRID, n_tasks=1, artefact_key='trace')

    run_slice(run_dir, bulky, task_index=1, quiet=True)

    assert len(list((run_dir / 'artefacts').glob('*.json'))) == 6


def test_an_artefact_is_keyed_by_combination_and_reads_back(tmp_path):
    run_dir = tmp_path / 'run'
    sweep = Sweep(evaluate=bulky)
    manifest = sweep.plan(run_dir, GRID, n_tasks=1, artefact_key='trace')
    run_slice(run_dir, bulky, task_index=1, quiet=True)

    combination = next(c for c in manifest.combinations if c['beta'] == 2)
    assert read_artefact(run_dir, combination['combination_id']) == [0, 1, 2, 3, 4, 5]


def test_an_artefact_is_kept_out_of_the_results_row(tmp_path):
    """The whole point: a row stays a row, and the bulk is addressable beside it."""
    run_dir = tmp_path / 'run'
    Sweep(evaluate=bulky).plan(run_dir, GRID, n_tasks=1, artefact_key='trace')

    run_slice(run_dir, bulky, task_index=1, quiet=True)

    records = read_parts(run_dir)
    assert all('trace' not in record for record in records)
    assert all(record['score'] in (1, 2, 3) for record in records)


def test_without_a_declared_key_the_value_stays_in_the_row(tmp_path):
    run_dir = tmp_path / 'run'
    Sweep(evaluate=bulky).plan(run_dir, GRID, n_tasks=1)

    run_slice(run_dir, bulky, task_index=1, quiet=True)

    assert all('trace' in record for record in read_parts(run_dir))
    assert not (run_dir / 'artefacts').exists()


def test_reading_an_artefact_that_was_never_kept_says_so(planned):
    with pytest.raises(FileNotFoundError, match='artefact key'):
        read_artefact(planned, 'deadbeef1234')


def test_the_artefact_key_is_recorded_on_the_manifest(tmp_path):
    """A run that kept artefacts must say so, or a later reader cannot tell them from absent ones."""
    run_dir = tmp_path / 'run'
    Sweep(evaluate=bulky).plan(run_dir, GRID, n_tasks=1, artefact_key='trace')

    assert Manifest.load(run_dir).artefact_key == 'trace'


# --- tuple parameters -----------------------------------------------------------------------------


TUPLE_GRID = {'window': [(1, 5), (2, 8)], 'alpha': [0.1]}


def test_a_tuple_parameter_survives_the_manifest(tmp_path):
    """JSON has no tuple, so without declaring it the evaluation silently receives a list."""
    run_dir = tmp_path / 'run'
    Sweep(evaluate=score).plan(run_dir, TUPLE_GRID, n_tasks=1, tuple_params=['window'])

    assert all(isinstance(c['window'], tuple) for c in Manifest.load(run_dir).combinations)


def test_an_undeclared_tuple_parameter_comes_back_as_a_list(tmp_path):
    """Pinning the behaviour the declaration exists to correct."""
    run_dir = tmp_path / 'run'
    Sweep(evaluate=score).plan(run_dir, TUPLE_GRID, n_tasks=1)

    assert all(isinstance(c['window'], list) for c in Manifest.load(run_dir).combinations)


def test_declaring_a_tuple_parameter_does_not_change_identity():
    """Ids must be stable across the declaration, or adding it orphans a run's completed work."""
    plain = [c['combination_id'] for c in expand_grid(TUPLE_GRID)]
    declared = [c['combination_id'] for c in expand_grid(TUPLE_GRID, tuple_params=['window'])]

    assert plain == declared


def test_restore_tuples_ignores_a_parameter_that_is_not_a_list():
    assert restore_tuples({'window': 5}, ['window']) == {'window': 5}


# --- reading the results table ----------------------------------------------------------------


def test_results_lead_with_the_run_s_own_parameters(sweep, tmp_path):
    run_dir = tmp_path / 'run'
    sweep.plan(run_dir, GRID, constants={'dataset': 'cora'}, n_tasks=1)
    run_slice(run_dir, sweep.evaluation, task_index=1, quiet=True)

    frame = collect_results(run_dir, write=False)

    assert list(frame.columns)[:4] == ['combination_id', 'dataset', 'alpha', 'beta']


def test_an_explicit_order_still_wins(sweep, planned):
    run_whole_array(sweep, planned)

    frame = collect_results(planned, write=False, leading=['score'])

    assert next(iter(frame.columns)) == 'score'


def test_the_constants_are_recorded_on_the_manifest(sweep, tmp_path):
    run_dir = tmp_path / 'run'
    sweep.plan(run_dir, GRID, constants={'dataset': 'cora'}, n_tasks=1)

    assert Manifest.load(run_dir).constants == {'dataset': 'cora'}


# --- configs ------------------------------------------------------------------------------------


def test_a_yaml_config_is_read(tmp_path):
    pytest.importorskip('yaml')
    config = tmp_path / 'sweep.yaml'
    config.write_text('grid:\n  alpha: [0.1, 0.2]\nnotes: from yaml\n', encoding='utf-8')

    assert read_config(config) == {'grid': {'alpha': [0.1, 0.2]}, 'notes': 'from yaml'}


def test_a_toml_config_is_still_the_default(tmp_path):
    config = tmp_path / 'sweep.toml'
    config.write_text('[grid]\nalpha = [0.1, 0.2]\n', encoding='utf-8')

    assert read_config(config)['grid'] == {'alpha': [0.1, 0.2]}


# --- the templates --------------------------------------------------------------------------------


@pytest.mark.parametrize('name', ['sweep.sbatch', 'job.sbatch', 'diagnose-env.sbatch'])
def test_every_template_ships_with_the_package(name):
    template = Path(__file__).parent.parent / 'src' / 'research_helpers' / 'templates' / name

    assert template.read_text(encoding='utf-8').startswith('#!/bin/bash')


# --- the dependency tier ---------------------------------------------------------------------


def test_importing_the_sweep_engine_pulls_in_nothing_third_party():
    """The path that runs on a cluster should have no dependencies outside the standard library."""
    subprocess.run(
        [
            sys.executable,
            '-c',
            (
                'import sys, research_helpers.sweep as s;'
                's.confidence_interval([1.0, 2.0, 3.0]);'
                "heavy = [m for m in ('pandas', 'numpy', 'scipy', 'pyarrow') if m in sys.modules];"
                'assert not heavy, heavy'
            ),
        ],
        check=True,
        capture_output=True,
    )


# --- what the command line actually prints ------------------------------------------------------


def test_status_prints_the_resubmission_command(sweep, planned, capsys):
    """The ported feature is the printed line, not just the key in the dict."""
    run_slice(planned, sweep.evaluation, task_index=2, quiet=True)

    sweep.main(['status', '--run-dir', str(planned)])

    output = capsys.readouterr().out
    assert '--array=1,3' in output
    assert 'Resubmit the unfinished slices' in output


def test_status_of_a_finished_run_suggests_nothing(sweep, planned, capsys):
    run_whole_array(sweep, planned)

    sweep.main(['status', '--run-dir', str(planned)])

    assert 'Resubmit' not in capsys.readouterr().out


def test_collecting_a_run_with_no_results_exits_non_zero(sweep, planned, capsys):
    (planned / 'parts').mkdir()

    assert sweep.main(['collect', '--run-dir', str(planned)]) == 1
    assert 'no results found' in capsys.readouterr().out


def test_collecting_an_empty_run_gives_an_empty_frame(planned):
    (planned / 'parts').mkdir()

    assert collect_results(planned, write=False).empty


def test_estimating_an_empty_grid_exits_non_zero(sweep, planned, capsys):
    assert sweep.main(['estimate', '--run-dir', str(planned), '--samples', '0']) == 1
    assert 'nothing to time' in capsys.readouterr().out


# --- configs that cannot be read ------------------------------------------------------------------


def test_a_yaml_config_without_pyyaml_says_what_to_install(tmp_path, monkeypatch):
    config = tmp_path / 'sweep.yaml'
    config.write_text('grid:\n  alpha: [0.1]\n', encoding='utf-8')
    monkeypatch.setitem(sys.modules, 'yaml', None)

    with pytest.raises(ImportError, match='needs pyyaml'):
        read_config(config)


# --- the results table without a manifest -----------------------------------------------------------


def test_collect_works_on_a_run_whose_manifest_is_gone(sweep, planned):
    """The ordering is a convenience read from the manifest, never a requirement for collecting."""
    run_whole_array(sweep, planned)
    (planned / 'manifest.json').unlink()

    frame = collect_results(planned, write=False)

    assert len(frame) == 6


def test_leading_columns_of_an_unplanned_run_is_empty(tmp_path):
    assert leading_columns(tmp_path) == []


# --- parquet, which is optional beside the CSV ------------------------------------------------------


def test_a_missing_parquet_engine_is_silent(sweep, planned, monkeypatch, capsys):
    """Parquet is a convenience; a warning would print on every collect of a working run."""
    run_whole_array(sweep, planned)
    monkeypatch.setattr(_collect, 'PARQUET_ENGINES', ('no_such_engine_xyz',))

    collect_results(planned)

    assert 'parquet' not in capsys.readouterr().out.lower()
    assert (planned / 'results.csv').exists()
    assert not (planned / 'results.parquet').exists()


def test_an_engine_that_cannot_take_the_frame_still_leaves_the_csv(sweep, planned, monkeypatch, capsys):
    run_whole_array(sweep, planned)

    def explode(*_args, **_kwargs):
        msg = 'contrived engine failure'
        raise ValueError(msg)

    monkeypatch.setattr('pandas.DataFrame.to_parquet', explode)
    collect_results(planned)

    assert 'parquet skipped' in capsys.readouterr().out
    assert (planned / 'results.csv').exists()


def test_a_list_valued_column_is_written_to_parquet_as_text(tmp_path):
    """Parquet has no representation for a column of lists, recording it as text beats failing."""
    pytest.importorskip('pyarrow')
    run_dir = tmp_path / 'run'
    listy = Sweep(evaluate=lambda _p, _c: {'sizes': [1, 2, 3]})
    listy.plan(run_dir, GRID, n_tasks=1)
    run_slice(run_dir, listy.evaluation, task_index=1, quiet=True)

    collect_results(run_dir)

    assert (run_dir / 'results.parquet').exists()


# --- making a result JSON-serialisable ----------------------------------------------------------------


class FakeScalar:
    """Anything with 'item' and 'dtype' is treated as a numpy scalar, without importing numpy."""

    dtype = 'float64'

    def item(self):
        return 0.5


def test_a_numpy_like_scalar_is_unwrapped(tmp_path):
    run_dir = tmp_path / 'run'
    Sweep().plan(run_dir, GRID, n_tasks=1)

    run_slice(run_dir, lambda _p, _c: {'score': FakeScalar()}, task_index=1, quiet=True)

    assert all(record['score'] == 0.5 for record in read_parts(run_dir))


def test_a_real_numpy_scalar_is_unwrapped(tmp_path):
    numpy = pytest.importorskip('numpy')
    run_dir = tmp_path / 'run'
    Sweep().plan(run_dir, GRID, n_tasks=1)

    run_slice(run_dir, lambda _p, _c: {'score': numpy.float64(2.5)}, task_index=1, quiet=True)

    assert all(record['score'] == 2.5 for record in read_parts(run_dir))


def test_tuples_and_sets_become_lists(tmp_path):
    run_dir = tmp_path / 'run'
    Sweep().plan(run_dir, GRID, n_tasks=1)

    run_slice(run_dir, lambda _p, _c: {'pair': (1, 2), 'seen': {3}}, task_index=1, quiet=True)

    record = read_parts(run_dir)[0]
    assert record['pair'] == [1, 2]
    assert record['seen'] == [3]


# --- surviving a task killed mid-write -----------------------------------------------------------------


def test_a_truncated_final_line_is_skipped_rather_than_fatal(sweep, planned):
    """The claim the guide makes about JSON Lines, on both readers."""
    run_slice(planned, sweep.evaluation, task_index=1, quiet=True)
    part = next((planned / 'parts').glob('*.jsonl'))
    with part.open('a', encoding='utf-8') as handle:
        handle.write('{"combination_id": "trunc')

    assert len(read_parts(planned)) == 2
    assert len(completed_ids(planned)) == 2


def test_completed_ids_of_a_run_that_never_started_is_empty(planned):
    assert completed_ids(planned) == set()


# --- the advice the command line gives ------------------------------------------------------------


def test_planning_a_very_wide_array_warns(sweep, tmp_path, capsys):
    """Schedulers push back past ~1000 elements, and the fix is per-task width, not task count."""
    wide = {'alpha': list(range(1100))}
    sweep.plan(tmp_path / 'run', wide, max_tasks=1100)
    (tmp_path / 'config.toml').write_text(
        'max_tasks = 1100\n\n[grid]\nalpha = [' + ','.join(str(i) for i in range(1100)) + ']\n',
        encoding='utf-8',
    )

    sweep.main(['plan', '--config', str(tmp_path / 'config.toml'), '--run-dir', str(tmp_path / 'run')])

    assert 'discourage arrays wider than' in capsys.readouterr().out


def test_estimate_flags_a_grid_whose_cost_varies_widely(tmp_path, capsys):
    """A mean is a poor guide to any single combination when the grid spans an order of magnitude."""

    def uneven(params, _context):
        time.sleep(0.002 * params['beta'] ** 3)
        return {'score': params['beta']}

    uneven_sweep = Sweep(evaluate=uneven)
    run_dir = tmp_path / 'run'
    uneven_sweep.plan(run_dir, GRID, n_tasks=1)

    uneven_sweep.main(['estimate', '--run-dir', str(run_dir), '--samples', '6'])

    output = capsys.readouterr().out
    assert 'wide spread across the grid' in output
    assert 'confidence interval on the mean' in output, 'the interval is a separate question'


def test_runs_dir_comes_from_the_project_settings(sweep, tmp_path, monkeypatch):
    (tmp_path / 'pyproject.toml').write_text(
        '[tool.research-helpers.sweep]\nruns-dir = "experiments"\n',
        encoding='utf-8',
    )
    monkeypatch.chdir(tmp_path)
    _load.cache_clear()

    # resolved against the project root, not left relative to the working directory
    assert sweep.runs_dir().is_absolute()
    assert sweep.runs_dir().name == 'experiments'


# --- jsonable as public API ----------------------------------------------------------------------


def test_jsonable_unwraps_a_numpy_like_scalar():
    assert jsonable(FakeScalar()) == 0.5


def test_jsonable_unwraps_a_real_numpy_scalar():
    numpy = pytest.importorskip('numpy')

    assert jsonable(numpy.float64(2.5)) == 2.5
    assert isinstance(jsonable(numpy.int64(3)), int)


def test_jsonable_renders_tuples_and_sets_as_lists():
    assert jsonable((1, 2)) == [1, 2]
    assert jsonable({3}) == [3]


def test_jsonable_reaches_into_nested_containers():
    """The conversion is the whole value, not its outermost layer."""
    assert jsonable({'a': [(1, 2), {3}]}) == {'a': [[1, 2], [3]]}


def test_jsonable_stringifies_dict_keys():
    """JSON object keys are strings. A numeric key would otherwise change type on the round trip."""
    assert jsonable({1: 'one'}) == {'1': 'one'}


def test_jsonable_leaves_ordinary_values_alone():
    for value in (1, 1.5, 'text', None, True, [1, 2]):
        assert jsonable(value) == value


def test_jsonable_output_actually_serialises():
    numpy = pytest.importorskip('numpy')

    json.dumps(jsonable({'f1': numpy.float64(0.83), 'window': (4, 12), 'seen': {1, 2}}))
