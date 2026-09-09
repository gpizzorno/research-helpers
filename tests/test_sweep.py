"""The sweep engine."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from research_helpers.project import _load
from research_helpers.sweep import (
    Manifest,
    Sweep,
    collect_results,
    combination_id,
    completed_ids,
    expand_grid,
    read_parts,
    run_slice,
    run_status,
    slice_bounds,
    task_index_from_env,
)

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
    with pytest.raises(FileNotFoundError, match='has the array run yet'):
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
