"""Shared matplotlib styling.

Includes two different profiles: 'screen' is roomy and readable in a notebook, 'print' is
sized to the LaTex document's own text width with everything scaled down to match its body text.

Styling reads 'research_helpers.project.FigureSettings', so the per-paper measurements come
from '[tool.research-helpers]' and can be overridden per call.

"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any

try:
    import matplotlib as mpl
    import matplotlib.pyplot as plt
    import seaborn as sns

except ModuleNotFoundError as error:  # pragma: no cover - exercised by installing without the extra
    msg = "research_helpers.figures needs matplotlib and seaborn: pip install 'research-helpers[figures]'"
    raise ModuleNotFoundError(msg) from error

from research_helpers.project import PROFILES, FigureSettings, Project, ProjectRootNotFoundError

if TYPE_CHECKING:
    from collections.abc import Iterator

    from matplotlib.axes import Axes
    from matplotlib.figure import Figure

__all__ = ['apply_style', 'current_settings', 'fit_x', 'save', 'style']

# screen profile
SCREEN_FIGSIZE = (12.0, 6.0)
SCREEN_FONT_SIZE = 11

# print profile
PRINT_HEIGHT_IN = 3.2
PRINT_FONT_SIZE = 8
PRINT_LINE_WIDTH = 1.2
PRINT_MARKER_SIZE = 3.0
PRINT_SECONDARY_SIZE = 'small'

DEFAULT_STYLE = 'bmh'
DEFAULT_TICK_DIRECTION = 'out'
DEFAULT_TITLE_SIZE = 'large'
DEFAULT_TITLE_PAD = 8.0
DEFAULT_LABEL_SIZE = 'medium'
DEFAULT_AXIS_MARGIN = 0.1
DEFAULT_GRID_COLOR = '#636363'
DEFAULT_GRID_ALPHA = 0.3
DEFAULT_LEGEND_FACE_COLOR = 'white'
DEFAULT_LABEL_PAD = 6.0
DEFAULT_EDGE_COLOR = '#999999'
DEFAULT_FACE_COLOR = '#eeeeee'
DEFAULT_LABEL_COLOR = 'black'
DEFAULT_LABEL_SPACING = 0.5
DEFAULT_CL_PAD = 0.04167
DEFAULT_CL_SPACE = 0.02

# display resolution
DISPLAY_DPI = 100

# overridable settings
SETTING_NAMES = tuple(FigureSettings.__dataclass_fields__)


def current_settings(**overrides: Any) -> FigureSettings:
    """Return the current figure settings, with 'overrides' applied on top.

    Reads '[tool.research-helpers.figures]' from the enclosing project if there is one, and
    falls back to package defaults otherwise.

    Arguments:
        **overrides: any field of 'FigureSettings'. A None is treated as 'not specified'.

    Returns:
        The resolved settings.

    """
    unknown = set(overrides) - set(SETTING_NAMES)
    if unknown:
        msg = f'unknown figure setting(s): {", ".join(sorted(unknown))}. Expected {", ".join(SETTING_NAMES)}'
        raise TypeError(msg)

    try:
        base = Project.from_pyproject().figures
    except ProjectRootNotFoundError:
        base = FigureSettings()

    given = {name: value for name, value in overrides.items() if value is not None}
    return FigureSettings(**{**{n: getattr(base, n) for n in SETTING_NAMES}, **given})


def apply_style(  # noqa: PLR0913
    *,
    profile: str | None = None,
    palette: str | None = None,
    font: str | None = None,
    dpi: int | None = None,
    text_width_in: float | None = None,
    column_width_in: float | None = None,
    figsize: tuple[float, float] | None = None,
    font_size: float | None = None,
    style_sheet: str = DEFAULT_STYLE,
    grid: bool = True,
) -> FigureSettings:
    r"""Apply the project's figure style to the current matplotlib session.

    Every rcParam is reset first, so repeated calls are idempotent and no earlier
    style can leak through.

    Arguments:
        profile: 'screen' or 'print'. Defaults to the project's setting.
        palette: seaborn palette name, e.g. 'husl', 'colorblind', 'deep'.
        font: sans-serif family name.
        dpi: resolution figures are saved at.
        text_width_in: the document's '\textwidth', i.e. the print profile's figure width.
        column_width_in: the document's '\columnwidth', for figures set in one column.
        figsize: explicit figure size in inches, overriding the profile's.
        font_size: explicit base font size in points, overriding the profile's.
        style_sheet: matplotlib style sheet supplying the base look.
        grid: whether axes carry a grid.

    Returns:
        The settings that were applied.

    Raises:
        ValueError: if 'profile' is not one of 'PROFILES'.

    """
    settings = current_settings(
        profile=profile,
        palette=palette,
        font=font,
        dpi=dpi,
        text_width_in=text_width_in,
        column_width_in=column_width_in,
    )
    if settings.profile not in PROFILES:
        msg = f'profile must be one of {PROFILES}, not {settings.profile!r}'
        raise ValueError(msg)

    printing = settings.profile == 'print'
    if figsize is None:
        figsize = (settings.text_width_in, PRINT_HEIGHT_IN) if printing else SCREEN_FIGSIZE
    if font_size is None:
        font_size = PRINT_FONT_SIZE if printing else SCREEN_FONT_SIZE

    # reset first so repeated calls are idempotent and a previous style cannot leak through,
    # then the style sheet, then the palette, then the explicit overrides below
    mpl.rcParams.update(mpl.rcParamsDefault)
    plt.style.use(style_sheet)
    sns.set_palette(settings.palette)

    plt.rcParams['axes.grid'] = grid
    plt.rcParams['figure.figsize'] = figsize
    plt.rcParams['font.size'] = font_size
    plt.rcParams['figure.dpi'] = DISPLAY_DPI
    plt.rcParams['savefig.dpi'] = settings.dpi
    plt.rcParams['font.family'] = 'sans-serif'
    plt.rcParams['font.sans-serif'] = [settings.font]
    plt.rcParams['xtick.direction'] = DEFAULT_TICK_DIRECTION
    plt.rcParams['ytick.direction'] = DEFAULT_TICK_DIRECTION
    plt.rcParams['axes.titlesize'] = DEFAULT_TITLE_SIZE
    plt.rcParams['axes.titlepad'] = DEFAULT_TITLE_PAD
    plt.rcParams['axes.labelsize'] = DEFAULT_LABEL_SIZE
    plt.rcParams['axes.xmargin'] = DEFAULT_AXIS_MARGIN
    plt.rcParams['axes.ymargin'] = DEFAULT_AXIS_MARGIN
    plt.rcParams['grid.color'] = DEFAULT_GRID_COLOR
    plt.rcParams['grid.alpha'] = DEFAULT_GRID_ALPHA
    plt.rcParams['legend.facecolor'] = DEFAULT_LEGEND_FACE_COLOR
    plt.rcParams['axes.labelpad'] = DEFAULT_LABEL_PAD
    plt.rcParams['axes.edgecolor'] = DEFAULT_EDGE_COLOR
    plt.rcParams['axes.facecolor'] = DEFAULT_FACE_COLOR
    plt.rcParams['axes.labelcolor'] = DEFAULT_LABEL_COLOR
    plt.rcParams['xtick.color'] = DEFAULT_GRID_COLOR
    plt.rcParams['xtick.labelcolor'] = 'inherit'
    plt.rcParams['ytick.color'] = DEFAULT_GRID_COLOR
    plt.rcParams['ytick.labelcolor'] = 'inherit'
    plt.rcParams['legend.edgecolor'] = DEFAULT_EDGE_COLOR
    plt.rcParams['legend.labelcolor'] = None
    plt.rcParams['legend.labelspacing'] = DEFAULT_LABEL_SPACING
    plt.rcParams['figure.constrained_layout.h_pad'] = DEFAULT_CL_PAD
    plt.rcParams['figure.constrained_layout.hspace'] = DEFAULT_CL_SPACE
    plt.rcParams['figure.constrained_layout.use'] = False
    plt.rcParams['figure.constrained_layout.w_pad'] = DEFAULT_CL_PAD
    plt.rcParams['figure.constrained_layout.wspace'] = DEFAULT_CL_SPACE

    if printing:
        _apply_print_overrides()

    return settings


def _apply_print_overrides() -> None:
    """Shrink the settings that do not follow 'font.size' on their own."""
    plt.rcParams['lines.linewidth'] = PRINT_LINE_WIDTH
    plt.rcParams['lines.markersize'] = PRINT_MARKER_SIZE
    plt.rcParams['legend.fontsize'] = PRINT_SECONDARY_SIZE
    plt.rcParams['xtick.labelsize'] = PRINT_SECONDARY_SIZE
    plt.rcParams['ytick.labelsize'] = PRINT_SECONDARY_SIZE
    plt.rcParams['axes.labelsize'] = PRINT_SECONDARY_SIZE
    plt.rcParams['axes.titlesize'] = 'medium'
    plt.rcParams['figure.titlesize'] = 'large'


@contextmanager
def style(**kwargs: Any) -> Iterator[FigureSettings]:
    """Apply a style for the duration of the block, then restore the previous rcParams.

    Takes the same arguments as 'apply_style'. For use in notebooks, where an
    'apply_style(profile="print")' would otherwise shrink every figure afterwards.

    Yields:
        The settings that were applied.

    """
    with mpl.rc_context():
        yield apply_style(**kwargs)


def save(
    figure: Figure,
    path: Path | str,
    *,
    tight: bool = True,
    pad_inches: float = 0.02,
    **kwargs: Any,
) -> Path:
    r"""Write a figure to 'path', creating the parent directory, and return the path.

    Arguments:
        figure: the figure to write.
        path: destination, including the extension, which selects the format.
        tight: crop to the drawn content. Pass 'False' to match width to the print profile.
        pad_inches: padding left around the content when 'tight'.
        **kwargs: passed to 'Figure.savefig', e.g. 'dpi' or 'transparent'.

    Returns:
        The path written.

    """
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    cropping = {'bbox_inches': 'tight', 'pad_inches': pad_inches} if tight else {}
    figure.savefig(destination, **cropping, **kwargs)
    return destination


def fit_x(figure: Figure, ax: Axes, pad: float = 0.1, passes: int = 2) -> None:
    """Narrow the x limits to what the axes actually draws, leaving 'pad' data units either side.

    Matplotlib's own margins work in data coordinates, so they leave too much room beside wide
    artists such as bar labels. Two passes are usually enough for the limits to settle.

    Arguments:
        figure: the figure holding 'ax'.
        ax: the axes to narrow.
        pad: data units to leave either side.
        passes: how many times to redraw and re-measure.

    """
    for _ in range(passes):
        figure.canvas.draw()
        renderer = figure.canvas.get_renderer()  # ty: ignore[unresolved-attribute]
        inverse = ax.transData.inverted()
        boxes = [artist.get_window_extent(renderer) for artist in (*ax.patches, *ax.texts, *ax.lines)]
        if not boxes:
            return
        left = inverse.transform((min(box.x0 for box in boxes), 0))[0]
        right = inverse.transform((max(box.x1 for box in boxes), 0))[0]
        ax.set_xlim(left - pad, right + pad)
