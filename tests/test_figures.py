"""Figure styling: profile behaviour, settings layers, and rcParam scoping."""

from __future__ import annotations

import matplotlib as mpl
import matplotlib.pyplot as plt
import pytest

mpl.use('Agg')  # no display in the test environment

from research_helpers.figures import (
    PRINT_FONT_SIZE,
    PRINT_HEIGHT_IN,
    SCREEN_FIGSIZE,
    SCREEN_FONT_SIZE,
    apply_style,
    current_settings,
    fit_x,
    save,
    style,
)
from research_helpers.project import FigureSettings, _load

SETTINGS = """
[tool.research-helpers.paper]
text-width-in = 5.5

[tool.research-helpers.figures]
profile = "print"
palette = "colorblind"
font = "Helvetica"
dpi = 300
"""


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path):
    """Style is global and a project is discovered from the working directory. Isolate both."""
    monkeypatch.delenv('RESEARCH_HELPERS_ROOT', raising=False)
    _load.cache_clear()
    # an unmarked directory, so tests see package defaults unless they make a project themselves
    workdir = tmp_path / 'nowhere'
    workdir.mkdir()
    monkeypatch.chdir(workdir)
    with mpl.rc_context():
        yield
    plt.close('all')
    _load.cache_clear()


@pytest.fixture
def configured(tmp_path, monkeypatch):
    """Return a project root whose pyproject.toml configures figures, and chdir into it."""
    root = tmp_path / 'project'
    root.mkdir()
    (root / 'pyproject.toml').write_text(SETTINGS, encoding='utf-8')
    monkeypatch.chdir(root)
    _load.cache_clear()
    return root


# --- settings resolution ----------------------------------------------------------------------


def test_defaults_apply_when_there_is_no_project():
    assert current_settings() == FigureSettings()


@pytest.mark.usefixtures('configured')
def test_the_project_supplies_settings():
    settings = current_settings()

    assert settings.profile == 'print'
    assert settings.palette == 'colorblind'
    assert settings.dpi == 300


@pytest.mark.usefixtures('configured')
def test_explicit_arguments_beat_the_project():
    settings = current_settings(palette='deep', dpi=72)

    assert settings.palette == 'deep'
    assert settings.dpi == 72
    assert settings.font == 'Helvetica', 'unspecified settings still come from the project'


@pytest.mark.usefixtures('configured')
def test_none_means_unspecified_rather_than_a_value():
    assert current_settings(palette=None).palette == 'colorblind'


def test_an_unknown_setting_is_a_programming_error():
    with pytest.raises(TypeError, match='unknown setting'):
        current_settings(colour_scheme='dark')


# --- profiles ---------------------------------------------------------------------------------


def test_the_screen_profile_sizes_for_a_notebook():
    apply_style(profile='screen')

    assert tuple(plt.rcParams['figure.figsize']) == SCREEN_FIGSIZE
    assert plt.rcParams['font.size'] == SCREEN_FONT_SIZE


@pytest.mark.usefixtures('configured')
def test_the_print_profile_takes_its_width_from_the_document():
    applied = apply_style()

    assert applied.profile == 'print'
    assert tuple(plt.rcParams['figure.figsize']) == (5.5, PRINT_HEIGHT_IN)
    assert plt.rcParams['font.size'] == PRINT_FONT_SIZE


def test_the_print_profile_shrinks_what_font_size_does_not_reach():
    apply_style(profile='print')

    assert plt.rcParams['xtick.labelsize'] == 'small'
    assert plt.rcParams['lines.markersize'] == 3.0


def test_an_unknown_profile_is_rejected():
    with pytest.raises(ValueError, match='profile must be one of'):
        apply_style(profile='poster')


@pytest.mark.usefixtures('configured')
def test_settings_reach_the_rcparams():
    apply_style()

    assert plt.rcParams['savefig.dpi'] == 300
    assert plt.rcParams['font.sans-serif'][0] == 'Helvetica'


def test_an_explicit_figsize_overrides_the_profile():
    apply_style(profile='print', figsize=(4.0, 2.0))

    assert tuple(plt.rcParams['figure.figsize']) == (4.0, 2.0)


# --- idempotency and scoping ------------------------------------------------------------------


def test_applying_twice_gives_the_same_result():
    apply_style(profile='print')
    once = dict(plt.rcParams)

    apply_style(profile='print')

    assert dict(plt.rcParams) == once


def test_switching_profiles_does_not_leak_the_previous_one():
    apply_style(profile='print')
    apply_style(profile='screen')
    after_switch = dict(plt.rcParams)

    apply_style(profile='screen')

    assert dict(plt.rcParams) == after_switch
    assert plt.rcParams['lines.markersize'] != 3.0, "the print profile's marker size survived"


def test_the_context_manager_restores_the_previous_style():
    apply_style(profile='screen')
    before = dict(plt.rcParams)

    with style(profile='print') as applied:
        assert applied.profile == 'print'
        assert plt.rcParams['font.size'] == PRINT_FONT_SIZE

    assert dict(plt.rcParams) == before


def test_the_context_manager_restores_even_when_the_block_raises():
    apply_style(profile='screen')
    before = dict(plt.rcParams)

    with pytest.raises(RuntimeError), style(profile='print'):
        raise RuntimeError

    assert dict(plt.rcParams) == before


# --- saving and fitting -----------------------------------------------------------------------


def test_save_creates_the_parent_directory_and_returns_the_path(tmp_path):
    figure, ax = plt.subplots()
    ax.plot([0, 1], [0, 1])
    destination = tmp_path / 'build' / 'figures' / 'curve.png'

    written = save(figure, destination)

    assert written == destination
    assert destination.stat().st_size > 0


def test_save_passes_keywords_through(tmp_path):
    figure, ax = plt.subplots()
    ax.plot([0, 1], [0, 1])

    small = save(figure, tmp_path / 'small.png', dpi=30)
    large = save(figure, tmp_path / 'large.png', dpi=200)

    assert large.stat().st_size > small.stat().st_size


def test_fit_x_narrows_the_limits_to_the_drawn_artists():
    apply_style(profile='screen')
    figure, ax = plt.subplots()
    ax.plot([2, 3], [0, 1])
    ax.set_xlim(-50, 50)

    fit_x(figure, ax, pad=0.1)

    left, right = ax.get_xlim()
    assert -1 < left < 2
    assert 3 < right < 6


def test_fit_x_leaves_empty_axes_alone():
    figure, ax = plt.subplots()
    ax.set_xlim(0, 1)

    fit_x(figure, ax)

    assert ax.get_xlim() == (0, 1)


def test_save_can_keep_the_full_figure_width(tmp_path):
    """A print figure must be able to come out at exactly the width it was laid out for."""
    from PIL import Image

    apply_style(profile='print', text_width_in=5.0, dpi=100)
    figure, ax = plt.subplots()
    ax.plot([0, 1], [0, 1])

    cropped = save(figure, tmp_path / 'cropped.png')
    full = save(figure, tmp_path / 'full.png', tight=False)

    assert Image.open(full).size[0] == 500, 'width should be text_width_in * dpi'
    assert Image.open(cropped).size[0] < 500
