"""Phase 0 scaffolding guarantees: the package installs, and importing it stays dependency-free."""

from __future__ import annotations

import subprocess
import sys

# Importing these must remain the caller's explicit choice, made by installing an extra. They are
# the dependencies that would otherwise creep back into the core import path.
OPTIONAL_DEPENDENCIES = ('matplotlib', 'seaborn', 'structlog', 'colorama', 'tqdm', 'pydantic')


def test_package_imports_and_reports_a_version():
    import research_helpers

    assert research_helpers.__version__
    assert research_helpers.__version__ != '0.0.0.dev0', 'package is not installed in this environment'


def test_importing_the_package_pulls_in_no_optional_dependency():
    """The core package must import with none of the extras installed.

    Run in a subprocess because this process has already imported some of them.
    """
    source = (
        'import sys; import research_helpers; '
        f'leaked = [n for n in {OPTIONAL_DEPENDENCIES!r} if n in sys.modules]; '
        'print(",".join(leaked))'
    )
    result = subprocess.run([sys.executable, '-c', source], capture_output=True, text=True, check=True)

    assert result.stdout.strip() == '', f'importing research_helpers pulled in: {result.stdout.strip()}'
