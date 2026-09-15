# Figures

The module aims to solve two main problems: figures that look different from each other because 
each notebook set its own `rcParams`, and figures that look pasted into the paper because they were 
authored at screen size and scaled down.

## Profiles

{py:func}`~research_helpers.figures.apply_style` applies a coherent look throughout. The specific
look is chosen via a `profile`:

`screen`
: Large (12×6 inches), default font sizes, 100 dpi on display. Intended for notebooks, where a 
  figure is looked at on its own.

`print`
: Sized to the document, with width taken from `paper.text-width-in`, and height from
  `figures.print-height-in`, 8pt fonts. A figure authored under this profile goes into the paper
  at 1:1 and its text comes out the same size as the surrounding body text.

```python
from research_helpers.figures import apply_style

apply_style()                    # the project's profile, defaults to 'screen'
apply_style(profile='print')     # paper geometry, paper font sizes
```

### Width and height

The width value is dictated by the document, the `width` setting is used to indicate
*which* of the document's two widths applies:

```python
apply_style(profile='print')                   # \textwidth, the default
apply_style(profile='print', width='column')   # \columnwidth, for one column of a two-column paper
```

The height is unconstrained, so it is a setting:

```toml
[tool.research-helpers.figures]
print-height-in = 3.2     # the default; -mm, -cm and -pt work too
```

Height can be overridden per call:

```python
apply_style(profile='print', print_height_in=4.5)
```

## Scoped styling

{py:func}`~research_helpers.figures.style` works as a context manager over
`matplotlib.rc_context`. It can be used in cases where one figure needs to differ 
without the details leaking into the rest of the notebook:

```python
from research_helpers.figures import style

with style(profile='print', palette='colorblind') as settings:
    fig, ax = plt.subplots()      # the profile's size is already in rcParams
    ...
```

The object returned is the resolved {py:class}`~research_helpers.project.FigureSettings`, which
carries `profile`, `palette`, `font` and `dpi`. The geometry is not on the profile—it
goes into `rcParams`, so `plt.subplots()` picks it up with no argument:

```python
>>> apply_style(profile='print')
FigureSettings(profile='print', palette='husl', font='DejaVu Sans', dpi=150, print_height_in=3.2)
>>> plt.rcParams['figure.figsize'], plt.rcParams['font.size']
([6.45, 3.2], 8.0)
```

## Saving versus rendering

{py:func}`~research_helpers.figures.save` writes to a file. {py:func}`~research_helpers.figures.render`
returns the identical bytes without touching the disk:

```python
save(fig, 'build/figures/learning-curve.png')
data = render(fig)                   # the same bytes, in memory
```

`render` exists for the build pipeline: an emitter registered with
{py:class}`~research_helpers.build.Registry` returns its artefact's content, and drift detection
compares that against the installed file byte for byte. A test asserts the two functions agree,
so the comparison is meaningful.

Both default to `tight=True`, which crops whitespace from the saved figure.

:::{note}
`tight=True` means that the saved image will be *narrower*, so a figure authored
at exactly `\textwidth` is not saved at exactly `\textwidth`. This is to prevent 
unnecessary white space, and `\includegraphics[width=\textwidth]`
will scale it correctly. This behaviour might be undesirable in certain situations, 
for example if trying to match a figure's width to a table's, in which case passing
`tight=False` will prevent the cropping altogether.
:::

## Long tick labels

{py:func}`~research_helpers.figures.fit_x` shrinks the x tick labels until they stop overlapping,
rather than rotating them:

```python
fit_x(fig, ax)
```

This is designed to help in situations where one wants to avoid rotating labels.

## Checking current settings

{py:func}`~research_helpers.figures.current_settings` resolves the project's figure settings
without applying anything (useful for troubleshooting):

```python
>>> current_settings().dpi
300
>>> current_settings(dpi=72).dpi     # an override, resolved the same way
72
```
