"""Assemble the arXiv submission from 'tex/'.

arXiv runs its own build, so the upload is source only: the manuscript, the ten generated tables,
the six figures, and the Biber-produced '.bbl'. Everything else in 'tex/' is either a build
artifact or a backup and must not be uploaded.

    python scripts/build_arxiv_submission.py --dry-run   # inventory and checks, write nothing
    python scripts/build_arxiv_submission.py             # build arxiv/dist/
    python scripts/build_arxiv_submission.py --tar       # and pack arxiv/dist.tar.gz
    python scripts/build_arxiv_submission.py --preview   # and build arxiv/preview/paper.pdf

"""

from __future__ import annotations

import argparse
import re
import shutil
import tarfile
from pathlib import Path

from bootstrapping.config import PROJECT_ROOT

TEX_DIR = PROJECT_ROOT / 'tex'
SUBMISSION_DIR = PROJECT_ROOT / 'arxiv'
DIST_DIR = SUBMISSION_DIR / 'dist'
# the preview is built somewhere else on purpose: arXiv rejects a .pdf submitted alongside .tex
# source, so no PDF and no build output may ever appear inside dist/
PREVIEW_DIR = SUBMISSION_DIR / 'preview'

ENGINE = 'xelatex'
PASSES = 3

MAIN = 'paper.tex'
BBL = 'paper.bbl'
# the .bbl is written beside the other build output, not next to the source
BBL_SOURCE = TEX_DIR / 'out_dir' / BBL

# arXiv's permitted filename characters
ALLOWED = re.compile(r'^[A-Za-z0-9_+,=.-]+$')
# TeX Live 2025 consumes this .bbl format; 2023 wants 3.2
EXPECTED_BBL_FORMAT = '3.3'


def sources() -> dict[str, Path]:
    """Return the upload set, keyed by the path it takes inside the submission."""
    files = {MAIN: TEX_DIR / MAIN, BBL: BBL_SOURCE}
    for table in sorted((TEX_DIR / 'tables').glob('*.tex')):
        files[f'tables/{table.name}'] = table
    for figure in sorted((TEX_DIR / 'figures').glob('*.png')):
        files[f'figures/{figure.name}'] = figure
    return files


def bbl_format(path: Path) -> str | None:
    """Return the format version declared in a biblatex .bbl, if it declares one."""
    if not path.exists():
        return None
    found = re.search(r'\$ biblatex bbl format version ([\d.]+) \$', path.read_text(encoding='utf-8'))
    return found.group(1) if found else None


def check(files: dict[str, Path]) -> list[str]:
    """Return every reason this submission would be rejected or would build wrongly."""
    problems = []

    missing = [name for name, path in files.items() if not path.exists()]
    problems += [f'missing: {name}' for name in missing]

    for name in files:
        if not all(ALLOWED.match(part) for part in name.split('/')):
            problems.append(f"filename outside arXiv's permitted characters: {name}")
        if any(part.startswith('.') for part in name.split('/')):
            problems.append(f'hidden file, arXiv rejects these: {name}')

    version = bbl_format(BBL_SOURCE)
    if version is None:
        problems.append(f'no {BBL} found at {BBL_SOURCE.relative_to(PROJECT_ROOT)}; run the build first')
    elif version != EXPECTED_BBL_FORMAT:
        problems.append(f'{BBL} is format {version}, TeX Live 2025 expects {EXPECTED_BBL_FORMAT}')

    # a .bbl older than the manuscript means citations may have changed since Biber last ran
    main = files.get(MAIN)
    if main and main.exists() and BBL_SOURCE.exists() and main.stat().st_mtime > BBL_SOURCE.stat().st_mtime:
        problems.append(f'{BBL} is older than {MAIN}; rebuild so Biber picks up any citation changes')

    # xetex has no font expansion, and microtype raises a hard error rather than ignoring it
    if main and main.exists() and 'expansion=true' in main.read_text(encoding='utf-8'):
        problems.append(
            f'{MAIN} sets microtype expansion=true, which is a hard error under {ENGINE}. Use expansion=false',
        )

    return problems


def build(files: dict[str, Path]) -> list[str]:
    """Copy the upload set into a freshly emptied 'arxiv/dist/'."""
    if DIST_DIR.exists():
        shutil.rmtree(DIST_DIR)
    written = []
    for name, source in files.items():
        destination = DIST_DIR / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        written.append(name)
    return written


def preview() -> Path:
    """Compile the built submission with the engine arXiv will use, outside dist/."""
    import subprocess  # noqa: PLC0415  -- only needed for the optional preview

    if PREVIEW_DIR.exists():
        shutil.rmtree(PREVIEW_DIR)
    shutil.copytree(DIST_DIR, PREVIEW_DIR)

    for _ in range(PASSES):
        subprocess.run(
            [ENGINE, '-interaction=nonstopmode', MAIN],
            cwd=PREVIEW_DIR,
            capture_output=True,
            check=False,
        )

    pdf = PREVIEW_DIR / 'paper.pdf'
    if not pdf.exists():
        msg = f'{ENGINE} produced no PDF; see {(PREVIEW_DIR / "paper.log").relative_to(PROJECT_ROOT)}'
        raise RuntimeError(msg)
    return pdf


def preview_report(pdf: Path) -> None:
    """Summarise the preview build the way the submission plan reports it."""
    log = (PREVIEW_DIR / 'paper.log').read_text(encoding='utf-8', errors='replace')
    pages = re.search(r'Output written on .*?\((\d+) pages', log)
    print(f'  engine    {ENGINE}')
    print(f'  pages     {pages.group(1) if pages else "?"}')
    for label, pattern in (
        ('errors', r'^!'),
        ('overfull', r'Overfull .hbox'),
        ('undefined cites', r'Citation .* undefined'),
        ('font substitutions', r'Font shape .* undefined'),
    ):
        print(f'  {label:<9} {len(re.findall(pattern, log, re.M))}')
    print(f'\n  {pdf.relative_to(PROJECT_ROOT)}')


def pack() -> Path:
    """Pack the built submission as the tarball arXiv accepts."""
    archive = SUBMISSION_DIR / 'dist.tar.gz'
    with tarfile.open(archive, 'w:gz') as tar:
        for path in sorted(DIST_DIR.rglob('*')):
            if path.is_file():
                tar.add(path, arcname=str(path.relative_to(DIST_DIR)))
    return archive


def report(files: dict[str, Path], problems: list[str]) -> None:
    """Print the manifest and anything wrong with it."""
    width = max(len(name) for name in files)
    total = 0
    for name, path in files.items():
        size = path.stat().st_size if path.exists() else 0
        total += size
        print(f'  {name:<{width}}  {size / 1024:>8.1f} KB' + ('' if path.exists() else '   MISSING'))
    print(f'\n  {len(files)} files, {total / 1024 / 1024:.2f} MB')

    version = bbl_format(BBL_SOURCE)
    if version:
        print(f'  bbl format {version} (TeX Live 2025)')

    if problems:
        print(f'\n{len(problems)} problem(s):')
        for problem in problems:
            print(f'  - {problem}')
    else:
        print('\nready to upload: select xelatex and TeX Live 2025')


def main() -> int:
    """Assemble the submission, or report what would go into it."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--dry-run', action='store_true', help='inventory and check without writing')
    parser.add_argument('--tar', action='store_true', help='also pack arxiv/dist.tar.gz')
    parser.add_argument(
        '--preview',
        action='store_true',
        help=f'also build arxiv/preview/paper.pdf with {ENGINE}, to see what arXiv will produce',
    )
    args = parser.parse_args()

    files = sources()
    problems = check(files)
    report(files, problems)

    if problems:
        return 1
    if args.dry_run:
        print('\n(dry run, nothing written)')
        return 0

    build(files)
    print(f'\nwrote {DIST_DIR.relative_to(PROJECT_ROOT)}/')
    if args.tar:
        archive = pack()
        print(f'packed {archive.relative_to(PROJECT_ROOT)} ({archive.stat().st_size / 1024 / 1024:.2f} MB)')
    if args.preview:
        print(f'\nbuilding preview with {ENGINE}...')
        preview_report(preview())
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
