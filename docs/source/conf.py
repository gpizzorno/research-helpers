"""Sphinx configuration for the research-helpers project."""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as package_version
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sphinx.application import Sphinx

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))

project = 'Research Helpers'
author = 'Gabe Pizzorno'
copyright = f'{datetime.now(tz=UTC):%Y}, {author}'  # noqa: A001

try:
    release = package_version('research-helpers')
except PackageNotFoundError:  # a checkout with nothing installed
    release = '0.0.0.dev0'
version = release.rsplit('.', 1)[0]

extensions = [
    'sphinx.ext.autodoc',
    'sphinx.ext.napoleon',
    'sphinx.ext.viewcode',
    'sphinx.ext.intersphinx',
    'sphinx_autodoc_typehints',  # must follow autodoc
    'sphinxcontrib.mermaid',
    'myst_parser',
]

exclude_patterns = ['_build', 'Thumbs.db', '.DS_Store']

# -- Markdown ----------------------------------------------------------------------------------

myst_enable_extensions = [
    'colon_fence',  # ::: fences, so admonitions survive a plain-Markdown reader
    'deflist',
    'attrs_inline',
]
myst_heading_anchors = 3

# -- autodoc -----------------------------------------------------------------------------------

autodoc_default_options = {
    'members': True,
    'member-order': 'bysource',
    'show-inheritance': True,
}
# Every module declares __all__ and honouring it keeps private helpers out of the reference without
# a second list here to drift out of step.
autodoc_default_options['ignore-module-all'] = False
autodoc_typehints = 'description'
autodoc_preserve_defaults = True

# Optional dependencies are installed for the docs build (the [docs] extra pulls them in) so that
# autodoc reads real signatures. This list is the fallback if that ever stops being true.
autodoc_mock_imports = []

always_use_bars_union = True
typehints_defaults = 'comma'
typehints_use_signature = False

napoleon_google_docstring = True
napoleon_numpy_docstring = False
napoleon_use_rtype = False

# project.py imports DataclassInstance from _typeshed under `if TYPE_CHECKING`. _typeshed has no
# runtime module, by design, so sphinx-autodoc-typehints cannot resolve the guarded import and
# warns. With -W in CI that would fail the build over a correctly written type-only import.
suppress_warnings = ['sphinx_autodoc_typehints.guarded_import']

# -- intersphinx -------------------------------------------------------------------------------

# Only the Python inventory. CI builds with -W, so an unreachable inventory is a build failure
intersphinx_mapping = {'python': ('https://docs.python.org/3', None)}
intersphinx_timeout = 10

# -- HTML --------------------------------------------------------------------------------------

html_theme = 'sphinx_rtd_theme'
html_static_path = ['_static']
html_css_files = ['custom.css']
html_theme_options = {
    'navigation_depth': 3,
    'collapse_navigation': False,
}

html_context = {
    'display_github': True,
    'github_user': 'gpizzorno',
    'github_repo': 'research-helpers',
    'github_version': 'main',
    'conf_py_path': '/docs/source/',
}

html_title = f'{project} v{version}'
html_short_title = 'Research Helpers'
html_favicon = None
html_logo = None

# If true, links to the reST sources are added to the pages.
html_show_sourcelink = False
# If true, "Created using Sphinx" is shown in the HTML footer.
html_show_sphinx = False
# If true, "(C) Copyright ..." is shown in the HTML footer.
html_show_copyright = True


# -- Suppressing module docstrings -------------------------------------------------------------

# autodoc has no directive option for this (`automodule` accepts members, exclude-members,
# imported-members and so on, but nothing that reaches the module docstring itself), so it has to
# be done by clearing the docstring on the event autodoc fires before rendering it.
#
# The reference pages each open with a hand-written description, and the module docstring repeats
# it directly underneath. Dropping it here keeps the page description in one place.


def _drop_module_docstring(
    _app: Sphinx,
    what: str,
    _name: str,
    _obj: object,
    _options: dict[str, Any],
    lines: list[str],
) -> None:
    """Discard a module's own docstring."""
    if what == 'module':
        lines.clear()  # in place, because autodoc reads this same list back


def setup(app: Sphinx) -> None:
    """Register the docstring filter."""
    app.connect('autodoc-process-docstring', _drop_module_docstring)
