"""Many sweeps through few arrays: plan lists, unit queues, running a block, and quarantine."""

from __future__ import annotations

from pathlib import Path

import pytest

from research_helpers.project import _load
from research_helpers.sweep import (
    ARTEFACTS_DIR,
    PARTS_DIR,
    Sweep,
    Unit,
    build_units,
    chunk,
    collect_results,
    expand_run_dirs,
    missing_task_indices,
    quarantine,
    read_plan_list,
    read_units,
    run_slice,
    select_run_dirs,
    shuffled,
    write_queues,
)

TEMPLATES = Path(__file__).parent.parent / 'src' / 'research_helpers' / 'templates'


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path):
    monkeypatch.delenv('RESEARCH_HELPERS_ROOT', raising=False)
    for name in ('SLURM_ARRAY_TASK_ID', 'SGE_TASK_ID', 'PBS_ARRAYID', 'LSB_JOBINDEX'):
        monkeypatch.delenv(name, raising=False)
    _load.cache_clear()
    monkeypatch.chdir(tmp_path)
    yield
    _load.cache_clear()


def score(params, context):
    """Evaluate one combination, keeping the cover aside as an artefact."""
    return {'score': params['alpha'] * params['beta'], 'cover': [params['alpha'], context['label']]}


def label(manifest, _run_dir):
    """Build the per-task context from the manifest."""
    return {'label': manifest.metadata['kind']}


@pytest.fixture
def sweep():
    """Return a sweep with an evaluation and a context registered."""
    return Sweep(evaluate=score, context=label)


@pytest.fixture
def campaign(tmp_path):
    """Two sweeps of four combinations over two slices each, and their plan list."""
    lines = []
    for name, kind in (('alpha', 'fast'), ('beta', 'slow')):
        config = tmp_path / f'{name}.toml'
        config.write_text(
            f'max_tasks = 2\nartefact_key = "cover"\n\n[metadata]\nkind = "{kind}"\n\n'
            '[grid]\nalpha = [1, 2]\nbeta = [3, 4]\n',
            encoding='utf-8',
        )
        lines.append(f'{name}.toml\truns/{name}')
    (tmp_path / 'PLAN.tsv').write_text('# generated\n\n' + '\n'.join(lines) + '\n', encoding='utf-8')
    return tmp_path


def planned(sweep):
    """Plan the campaign and return its two run directories."""
    assert sweep.main(['plan-list', '--list', 'PLAN.tsv']) == 0
    return [Path('runs/alpha'), Path('runs/beta')]


# --- plan lists and run directories ---------------------------------------------------------------


def test_a_plan_list_is_read_and_a_malformed_line_is_refused(tmp_path):
    good = tmp_path / 'good.tsv'
    good.write_text('# comment\n\na.toml\truns/a\n', encoding='utf-8')
    assert read_plan_list(good) == [(Path('a.toml'), Path('runs/a'))]

    bad = tmp_path / 'bad.tsv'
    bad.write_text('a.toml runs/a\n', encoding='utf-8')
    with pytest.raises(ValueError, match=r'bad\.tsv:1'):
        read_plan_list(bad)


@pytest.mark.usefixtures('campaign')
def test_plan_list_plans_every_sweep_in_one_process(sweep, capsys):
    runs = planned(sweep)

    assert all((run_dir / 'manifest.json').exists() for run_dir in runs)
    assert 'planned 2 sweeps: 8 combinations in 4 slices' in capsys.readouterr().out


@pytest.mark.usefixtures('campaign')
def test_run_dirs_expand_from_globs_and_refuse_unplanned_paths(sweep):
    runs = planned(sweep)

    assert expand_run_dirs(['runs/*']) == runs
    assert expand_run_dirs(['runs/alpha', 'runs/a*']) == [runs[0]], 'no duplicates'
    with pytest.raises(FileNotFoundError, match='not a planned run directory'):
        expand_run_dirs(['runs'])
    with pytest.raises(FileNotFoundError, match='matches no planned'):
        expand_run_dirs(['runs/z*'])


@pytest.mark.usefixtures('campaign')
def test_sweeps_are_selected_by_what_their_manifests_record(sweep):
    runs = planned(sweep)

    assert select_run_dirs(runs, where={'kind': ['slow']}) == [runs[1]]
    assert select_run_dirs(runs, where_not={'kind': ['slow']}) == [runs[0]]
    assert select_run_dirs(runs, where={'kind': ['fast', 'slow']}) == runs
    assert select_run_dirs(runs, where={'absent': ['x']}) == [], 'a key the manifest lacks matches nothing'
    assert select_run_dirs(runs, where_not={'absent': ['x']}) == runs


def test_constants_are_selectable_and_compared_as_text(sweep, tmp_path):
    sweep.plan(tmp_path / 'a', {'alpha': [1]}, constants={'depth': 3})
    sweep.plan(tmp_path / 'b', {'alpha': [1]}, constants={'depth': 10})

    assert select_run_dirs([tmp_path / 'a', tmp_path / 'b'], where={'depth': ['10']}) == [tmp_path / 'b']


# --- units and queue files ----------------------------------------------------------------------


def test_every_slice_is_one_unit_and_chunks_respect_the_array_width():
    units = [Unit('r', task) for task in range(1, 26)]
    parts = chunk(units, per_task=3, max_array=4)

    assert [len(part) for part in parts] == [12, 12, 1]
    assert [unit for part in parts for unit in part] == units
    with pytest.raises(ValueError, match='at least 1'):
        chunk(units, per_task=0, max_array=4)


def test_an_element_reads_exactly_its_block(tmp_path):
    units = [Unit(f'runs/s{task % 3}', task) for task in range(1, 8)]
    [(path, width)] = write_queues(units, tmp_path / 'q', per_task=3)

    assert width == 3
    blocks = [read_units(path, element, 3) for element in (1, 2, 3)]
    assert [unit for block in blocks for unit in block] == units
    assert read_units(path, 4, 3) == [], 'past the end of the file'
    with pytest.raises(ValueError, match='at least 1'):
        read_units(path, 0, 3)


def test_a_malformed_unit_is_refused(tmp_path):
    queue = tmp_path / 'q.units'
    queue.write_text('runs/a 1\n', encoding='utf-8')

    with pytest.raises(ValueError, match='malformed unit'):
        read_units(queue, 1, 1)


def test_a_live_queue_is_not_overwritten_and_a_forced_rewrite_prunes_it(tmp_path):
    """Pending elements read their block when they start, so rewriting their file misroutes them."""
    units = [Unit('r', task) for task in range(1, 10)]
    write_queues(units, tmp_path / 'q', per_task=1, max_array=3)
    assert len(list(tmp_path.glob('q.*.units'))) == 3

    with pytest.raises(FileExistsError, match='new stem'):
        write_queues(units[:2], tmp_path / 'q', per_task=1, max_array=3)
    write_queues(units[:2], tmp_path / 'q', per_task=1, max_array=3, force=True)
    assert [path.name for path in tmp_path.glob('q.*.units')] == ['q.01.units']


def test_a_stem_with_glob_characters_still_finds_its_own_queue(tmp_path):
    write_queues([Unit('r', 1)], tmp_path / 'q[1]', per_task=1)

    with pytest.raises(FileExistsError):
        write_queues([Unit('r', 1)], tmp_path / 'q[1]', per_task=1)


def test_the_array_width_comes_from_the_project_settings(tmp_path):
    (tmp_path / 'pyproject.toml').write_text('[tool.research-helpers.sweep]\nmax-array = 2\n', encoding='utf-8')
    _load.cache_clear()
    units = [Unit('r', task) for task in range(1, 6)]

    written = write_queues(units, tmp_path / 'q', per_task=1)

    assert [width for _path, width in written] == [2, 2, 1]


def test_a_shuffled_queue_is_the_same_units_in_a_seeded_order():
    units = [Unit(f'runs/s{n // 10}', n % 10 + 1) for n in range(100)]
    mixed = shuffled(units, 7)

    assert mixed != units
    assert sorted(mixed, key=Unit.line) == sorted(units, key=Unit.line)
    assert shuffled(units, 7) == mixed, 'a regenerated queue must be the same queue'
    assert len({unit.run_dir for unit in mixed[:10]}) > 1, 'an element should draw from more than one sweep'


# --- running a queue ------------------------------------------------------------------------------


@pytest.mark.usefixtures('campaign')
def test_the_queue_runs_every_slice_once_and_pending_finds_what_is_left(sweep, capsys):
    runs = planned(sweep)
    assert sweep.main(['queue', '--list', 'PLAN.tsv', '--out', 'queues/toy', '--per-task', '3']) == 0
    assert 'sbatch --array=1-2 <your queue script> queues/toy.01.units 3' in capsys.readouterr().out

    # element 1 runs three of the four slices; the fourth is left for a resumed queue
    assert sweep.main(['run-units', '--units', 'queues/toy.01.units', '--per-task', '3', '--element', '1']) == 0
    assert missing_task_indices(runs[0]) == []
    assert missing_task_indices(runs[1]) == [2]
    assert build_units(runs, pending=True) == [Unit(str(runs[1]), 2)]

    sweep.main(['queue', '--run-dir', 'runs/*', '--out', 'queues/toy_r1', '--per-task', '3', '--pending'])
    assert Path('queues/toy_r1.01.units').read_text(encoding='utf-8') == f'{runs[1]}\t2\n'
    assert sweep.main(['run-units', '--units', 'queues/toy_r1.01.units', '--per-task', '3', '--element', '1']) == 0

    assert sweep.main(['collect', '--run-dir', 'runs/*']) == 0
    for run_dir in runs:
        frame = collect_results(run_dir, write=False)
        assert len(frame) == 4
        assert frame['combination_id'].is_unique


@pytest.mark.usefixtures('campaign')
def test_a_campaign_is_queued_in_parts_by_what_its_manifests_record(sweep):
    planned(sweep)

    sweep.main(['queue', '--run-dir', 'runs/*', '--where', 'kind=slow', '--out', 'q/slow', '--per-task', '5'])
    sweep.main(['queue', '--run-dir', 'runs/*', '--where-not', 'kind=slow', '--out', 'q/fast', '--per-task', '5'])

    slow = {line.split('\t')[0] for line in Path('q/slow.01.units').read_text(encoding='utf-8').splitlines()}
    fast = {line.split('\t')[0] for line in Path('q/fast.01.units').read_text(encoding='utf-8').splitlines()}
    assert slow == {'runs/beta'}
    assert fast == {'runs/alpha'}


@pytest.mark.usefixtures('campaign')
def test_a_failing_unit_does_not_stop_its_block(sweep, capsys):
    planned(sweep)
    Path('mixed.units').write_text('runs/missing\t1\nruns/alpha\t1\n', encoding='utf-8')

    assert sweep.main(['run-units', '--units', 'mixed.units', '--per-task', '2', '--element', '1']) == 1
    assert 'FAILED runs/missing\t1' in capsys.readouterr().err
    assert missing_task_indices('runs/alpha') == [2], 'the unit after the failure still ran'


@pytest.mark.usefixtures('campaign')
def test_the_context_is_built_afresh_for_every_unit():
    """A context shared between slices could carry one slice's state into another's results."""
    built = []

    def context(manifest, run_dir):
        built.append(run_dir)
        return {'label': manifest.metadata['kind']}

    sweep = Sweep(evaluate=score, context=context)
    sweep.main(['plan-list', '--list', 'PLAN.tsv'])
    Path('q.units').write_text('runs/alpha\t1\nruns/alpha\t2\n', encoding='utf-8')

    sweep.main(['run-units', '--units', 'q.units', '--per-task', '2', '--element', '1'])

    assert built == [Path('runs/alpha'), Path('runs/alpha')]


@pytest.mark.usefixtures('campaign')
def test_the_element_comes_from_the_scheduler(sweep, monkeypatch):
    planned(sweep)
    sweep.main(['queue', '--run-dir', 'runs/*', '--out', 'q', '--per-task', '1'])
    monkeypatch.setenv('SLURM_ARRAY_TASK_ID', '3')

    assert sweep.main(['run-units', '--units', 'q.01.units', '--per-task', '1']) == 0
    assert missing_task_indices('runs/beta') == [2], 'element 3 is the third unit, beta slice 1'


def test_queue_needs_to_be_told_which_sweeps(sweep, capsys):
    assert sweep.main(['queue', '--out', 'q', '--per-task', '1']) == 1
    assert '--run-dir' in capsys.readouterr().err


@pytest.mark.usefixtures('campaign')
def test_queue_refuses_to_rewrite_a_live_queue_without_a_traceback(sweep, capsys):
    planned(sweep)
    sweep.main(['queue', '--run-dir', 'runs/*', '--out', 'q', '--per-task', '1'])

    assert sweep.main(['queue', '--run-dir', 'runs/*', '--out', 'q', '--per-task', '1']) == 1
    assert 'exists' in capsys.readouterr().err


@pytest.mark.usefixtures('campaign')
def test_a_finished_campaign_has_nothing_pending(sweep, capsys):
    runs = planned(sweep)
    for unit in build_units(runs):
        sweep.run_unit(unit)
    capsys.readouterr()

    assert sweep.main(['queue', '--run-dir', 'runs/*', '--out', 'q', '--per-task', '1', '--pending']) == 0
    assert 'nothing pending' in capsys.readouterr().out
    assert not list(Path().glob('q.*.units'))


@pytest.mark.usefixtures('campaign')
def test_a_malformed_where_is_an_argument_error(sweep):
    planned(sweep)

    with pytest.raises(SystemExit):
        sweep.main(['queue', '--run-dir', 'runs/*', '--where', 'kind', '--out', 'q', '--per-task', '1'])


# --- status and collect over many sweeps -------------------------------------------------------


@pytest.mark.usefixtures('campaign')
def test_status_over_many_sweeps_gives_a_line_each(sweep, capsys):
    runs = planned(sweep)
    run_slice(runs[0], score, task_index=1, context={'label': 'fast'}, quiet=True)
    capsys.readouterr()

    assert sweep.main(['status', '--run-dir', 'runs/*']) == 0

    printed = capsys.readouterr().out
    assert 'runs/alpha  2/4   50.0%  unfinished slices 2' in printed
    assert 'runs/beta   0/4    0.0%  unfinished slices 1-2' in printed
    assert '0 of 2 sweeps finished' in printed
    assert 'queue --pending' in printed


@pytest.mark.usefixtures('campaign')
def test_collecting_many_sweeps_names_the_ones_with_nothing_yet(sweep, capsys):
    runs = planned(sweep)
    run_slice(runs[0], score, task_index=1, context={'label': 'fast'}, quiet=True)
    (runs[1] / PARTS_DIR).mkdir()

    assert sweep.main(['collect', '--run-dir', 'runs/*']) == 1

    printed = capsys.readouterr().out
    assert 'collected 1 of 2 sweeps' in printed
    assert 'no results yet: runs/beta' in printed


# --- elements that ran twice at once -------------------------------------------------------------


def ran(sweep):
    """Plan and run the whole toy campaign through a queue of two elements."""
    runs = planned(sweep)
    sweep.main(['queue', '--list', 'PLAN.tsv', '--out', 'queues/toy', '--per-task', '3'])
    for element in ('1', '2'):
        assert sweep.main(['run-units', '--units', 'queues/toy.01.units', '--per-task', '3', '--element', element]) == 0
    return Path('queues/toy.01.units'), runs


@pytest.mark.usefixtures('campaign')
def test_a_nul_tail_swallows_the_line_a_resumed_task_appends(sweep):
    """Why a doubly-run unit is set aside rather than resumed: its next line is glued and lost."""
    queue, runs = ran(sweep)
    part = runs[1] / PARTS_DIR / 'task-00002.jsonl'
    part.write_bytes(b'\x00' * 40)  # what two nodes appending to one file left behind

    assert missing_task_indices(runs[1]) == [2]
    sweep.run_unit(Unit(str(runs[1]), 2))
    assert missing_task_indices(runs[1]) == [2], 'the rerun wrote its line onto the NULs'

    assert sweep.main(['quarantine', '--units', str(queue), '--per-task', '3', '--elements', '2', '--apply']) == 0
    sweep.run_unit(Unit(str(runs[1]), 2))
    assert missing_task_indices(runs[1]) == []


@pytest.mark.usefixtures('campaign')
def test_quarantine_sets_aside_parts_and_artefacts_and_pending_reruns_them(sweep, capsys):
    queue, runs = ran(sweep)
    damaged = runs[0] / PARTS_DIR / 'task-00001.jsonl'
    damaged.write_bytes(damaged.read_bytes() + b'\x00' * 40)
    before = {path: path.read_bytes() for path in Path().rglob('*') if path.is_file()}
    capsys.readouterr()

    assert sweep.main(['quarantine', '--units', str(queue), '--per-task', '3', '--elements', '1']) == 0
    assert '3 units, 3 part files, 1 damaged part files, 6 artefacts' in capsys.readouterr().out
    assert {path: path.read_bytes() for path in Path().rglob('*') if path.is_file()} == before, (
        'a dry run changes nothing'
    )

    assert sweep.main(['quarantine', '--units', str(queue), '--per-task', '3', '--elements', '1', '--apply']) == 0
    assert 'set aside 9 file(s)' in capsys.readouterr().out
    assert sorted(path.name for path in (runs[0] / PARTS_DIR).iterdir()) == [
        'task-00001.jsonl.quarantined',
        'task-00002.jsonl.quarantined',
    ]
    assert build_units(runs, pending=True) == [Unit(str(runs[0]), 1), Unit(str(runs[0]), 2), Unit(str(runs[1]), 1)]

    sweep.main(['queue', '--run-dir', 'runs/*', '--out', 'queues/toy_r1', '--per-task', '3', '--pending'])
    assert sweep.main(['run-units', '--units', 'queues/toy_r1.01.units', '--per-task', '3', '--element', '1']) == 0
    capsys.readouterr()
    assert sweep.main(['collect', '--run-dir', 'runs/*']) == 0
    assert 'malformed' not in capsys.readouterr().out
    for run_dir in runs:
        assert len(collect_results(run_dir, write=False)) == 4
        assert len(list((run_dir / ARTEFACTS_DIR).glob('*.json'))) == 4


@pytest.mark.usefixtures('campaign')
def test_a_second_quarantine_never_overwrites_the_first(sweep):
    _queue, runs = ran(sweep)
    unit = Unit(str(runs[0]), 1)

    quarantine([unit], apply=True)
    sweep.run_unit(unit)
    quarantine([unit], apply=True)

    names = sorted(path.name for path in (runs[0] / PARTS_DIR).iterdir())
    assert names == ['task-00001.jsonl.quarantined', 'task-00001.jsonl.quarantined.2', 'task-00002.jsonl']


def test_quarantine_reads_artefacts_from_another_directory_when_told(sweep, tmp_path):
    """A project whose runs keep artefacts under another name, e.g. 'covers'."""
    run_dir = tmp_path / 'run'
    manifest = sweep.plan(run_dir, {'alpha': [1], 'beta': [2]}, metadata={'kind': 'x'})
    run_slice(run_dir, score, task_index=1, context={'label': 'x'}, quiet=True)
    [combination] = manifest.combinations
    (run_dir / 'covers').mkdir()
    (run_dir / 'covers' / f'{combination["combination_id"]}.json').write_text('[]', encoding='utf-8')

    counts = quarantine([Unit(str(run_dir), 1)], artefacts_dir='covers', apply=True)

    assert counts['artefacts'] == 1
    assert counts['set aside'] == 2, 'the part file and the cover'
    assert not list((run_dir / 'covers').glob('*.json'))


# --- the template ---------------------------------------------------------------------------------


def _environment(name):
    """Return a template's environment block: module loads, activation, interpreter checks, thread caps."""
    text = (TEMPLATES / name).read_text(encoding='utf-8')
    return text[text.index('mkdir -p logs') : text.index('echo "python=$PYTHON"')]


def test_the_queue_template_sets_up_the_job_exactly_as_the_sweep_template_does():
    """Every failure the block guards against has happened; a copy that drifted would bring one back."""
    assert _environment('queue.sbatch') == _environment('sweep.sbatch')
    assert 'run-units' in (TEMPLATES / 'queue.sbatch').read_text(encoding='utf-8')


@pytest.mark.parametrize('name', ['sweep.sbatch', 'queue.sbatch'])
def test_array_templates_refuse_a_requeue(name):
    """A re-queued element can run beside its still-running original, and both append to one file."""
    assert '#SBATCH --no-requeue' in (TEMPLATES / name).read_text(encoding='utf-8')
