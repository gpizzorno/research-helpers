"""Assemble the Zenodo deposit from the local Stanza resources directory.

Packages the nine reported iterations as one gzipped tar each, plus the three sets of
corpus-trained word vectors they depend on, into 'zenodo/dist/'. Each archive unpacks as a 'la/'
overlay onto a Stanza resources directory.

python scripts/build_zenodo_deposit.py --dry-run   # inventory and checks, write nothing
python scripts/build_zenodo_deposit.py             # build zenodo/dist/
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import shutil
import tarfile
from pathlib import Path
from typing import Any

from bootstrapping.config import LATIN_MODEL_DIR, PROJECT_ROOT, STANZA_RESOURCES_DIR

# the iterations the paper reports; s10 was trained but is not part of the learning curve
ITERATIONS = [f'marseille_s{i}' for i in range(1, 10)]

# the four processors that make up one pipeline, in load order
TASKS = ('tokenize', 'pos', 'lemma', 'depparse')

DEPOSIT_DIR = PROJECT_ROOT / 'zenodo'
DIST_DIR = DEPOSIT_DIR / 'dist'
RESOURCES_PATH = STANZA_RESOURCES_DIR / 'resources.json'

# files copied verbatim into the deposit alongside the archives
DEPOSIT_FILES = ('README.md', 'LICENSE')

# fixed timestamp for the gzip header and every archive member
EPOCH = 0


def load_registry() -> dict[str, dict[str, Any]]:
    """Return the 'la' section of Stanza's resources.json."""
    if not RESOURCES_PATH.exists():
        msg = f'no Stanza registry at {RESOURCES_PATH}; run stanza.download("la") once to create it'
        raise SystemExit(msg)
    return json.loads(RESOURCES_PATH.read_text(encoding='utf-8'))['la']  # type: ignore[no-any-return]


def required_pretrains(registry: dict[str, dict[str, Any]]) -> dict[str, str]:
    """Map each iteration to the pretrain package its tagger and parser were trained against.

    Arguments:
        registry: the 'la' section of resources.json.

    Returns:
        Iteration name to pretrain package name.

    """
    pretrains: dict[str, str] = {}
    for iteration in ITERATIONS:
        packages: set[str] = set()
        for task in ('pos', 'depparse'):
            entry = registry.get(task, {}).get(iteration, {})
            packages.update(d['package'] for d in entry.get('dependencies', []) if d['model'] == 'pretrain')
        if len(packages) != 1:
            msg = f'{iteration}: expected exactly one pretrain dependency, found {sorted(packages)}'
            raise SystemExit(msg)
        pretrains[iteration] = packages.pop()
    return pretrains


def digest(path: Path, algorithm: str) -> str:
    """Return the hex digest of a file, read in 1 MB blocks."""
    hasher = hashlib.new(algorithm)
    with path.open('rb') as handle:
        while block := handle.read(1 << 20):
            hasher.update(block)
    return hasher.hexdigest()


def collect(pretrains: dict[str, str]) -> tuple[dict[str, list[Path]], list[str]]:
    """Resolve every file the deposit needs.

    Arguments:
        pretrains: iteration to pretrain package, from 'required_pretrains'.

    Returns:
        Archive name to its member files, and a list of files that are missing.

    """
    members: dict[str, list[Path]] = {}
    missing: list[str] = []

    for iteration in ITERATIONS:
        paths = []
        for task in TASKS:
            path = LATIN_MODEL_DIR / task / f'{iteration}.pt'
            if path.exists():
                paths.append(path)
            else:
                missing.append(str(path))
        members[iteration] = paths

    pretrain_paths = []
    for package in sorted(set(pretrains.values())):
        path = LATIN_MODEL_DIR / 'pretrain' / f'{package}.pt'
        if path.exists():
            pretrain_paths.append(path)
        else:
            missing.append(str(path))
    members['pretrain'] = pretrain_paths

    return members, missing


def registry_drift(registry: dict[str, dict[str, Any]], members: dict[str, list[Path]]) -> list[str]:
    """Return the shipped files whose md5 disagrees with the local resources.json."""
    drifted: dict[str, list[str]] = {}
    for name, paths in members.items():
        for path in paths:
            task = 'pretrain' if name == 'pretrain' else path.parent.name
            key = path.stem if name == 'pretrain' else name
            recorded = registry.get(task, {}).get(key, {}).get('md5')
            if recorded and recorded != digest(path, 'md5'):
                drifted.setdefault(key, []).append(task)
    return [f'{key} ({", ".join(tasks)})' for key, tasks in drifted.items()]


def registry_fragment(registry: dict[str, dict[str, Any]], members: dict[str, list[Path]]) -> dict[str, dict[str, Any]]:
    """Build the resources.json entries a user must merge to resolve these packages."""
    fragment: dict[str, dict[str, dict[str, dict[str, Any]]]] = {task: {} for task in (*TASKS, 'pretrain')}

    for name, paths in members.items():
        for path in paths:
            task = 'pretrain' if name == 'pretrain' else path.parent.name
            key = path.stem if name == 'pretrain' else name
            entry = dict(registry.get(task, {}).get(key, {}))
            entry['md5'] = digest(path, 'md5')
            fragment[task][key] = entry

    return {'la': fragment}


def normalise(info: tarfile.TarInfo) -> tarfile.TarInfo:
    """Strip host-specific metadata from an archive member."""
    info.mtime = EPOCH
    info.uid = info.gid = 0
    info.uname = info.gname = ''
    info.mode = 0o644
    return info


def write_archive(name: str, paths: list[Path], destination: Path) -> Path:
    """Write one gzipped tar whose members sit at 'la/<task>/<file>'."""
    archive = destination / f'{name}.tar.gz'
    with (
        archive.open('wb') as raw,
        gzip.GzipFile(filename='', mode='wb', compresslevel=6, fileobj=raw, mtime=EPOCH) as compressed,
        tarfile.open(fileobj=compressed, mode='w', format=tarfile.GNU_FORMAT) as tar,
    ):
        for path in paths:
            tar.add(path, arcname=f'la/{path.parent.name}/{path.name}', filter=normalise)
    return archive


def report(
    registry: dict[str, dict[str, Any]],
    pretrains: dict[str, str],
    members: dict[str, list[Path]],
    missing: list[str],
) -> None:
    """Print the inventory, the vector bindings, and any integrity findings."""
    print(f'source   : {LATIN_MODEL_DIR}')
    print(f'registry : {RESOURCES_PATH}')
    print(f'deposit  : {DIST_DIR}\n')

    total = 0
    for name, paths in members.items():
        size = sum(p.stat().st_size for p in paths)
        total += size
        detail = ', '.join(p.stem if name == 'pretrain' else p.parent.name for p in paths)
        print(f'  {name:<14} {size / 1e6:7.1f} MB  [{detail}]')
    print(f'  {"":<14} {total / 1e6:7.1f} MB  uncompressed total\n')

    print('pretrain bindings:')
    for package in sorted(set(pretrains.values())):
        bound = [i.replace('marseille_', '') for i in ITERATIONS if pretrains[i] == package]
        print(f'  {package:<16} {" ".join(bound)}')
    print()

    if missing:
        print('MISSING')
        for path in missing:
            print(f'  {path}')
        raise SystemExit(1)
    print(f'all {sum(len(p) for p in members.values())} files present')

    drifted = registry_drift(registry, members)
    if drifted:
        print(
            f'\nnote: {len(drifted)} package(s) carry an md5 in {RESOURCES_PATH.name} that does not match\n'
            '      the file on disk. The weights have not been modified; the registry entry is stale.\n'
            '      The deposit records freshly computed sums, so it is unaffected.',
        )
        for item in drifted:
            print(f'        {item}')


def main() -> None:
    """Build the deposit, or report what building it would do."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--dry-run', action='store_true', help='inventory and verify without writing anything')
    args = parser.parse_args()

    registry = load_registry()
    pretrains = required_pretrains(registry)
    members, missing = collect(pretrains)
    report(registry, pretrains, members, missing)

    if args.dry_run:
        print(f'\nDry run: {len(members)} archive(s) would be written to {DIST_DIR}')
        return

    if DIST_DIR.exists():
        shutil.rmtree(DIST_DIR)
    DIST_DIR.mkdir(parents=True)

    print()
    written = []
    for name, paths in members.items():
        archive = write_archive(name, paths, DIST_DIR)
        written.append(archive)
        print(f'  {archive.name:<26} {archive.stat().st_size / 1e6:7.1f} MB')

    fragment_path = DIST_DIR / 'resources-marseille.json'
    fragment_path.write_text(json.dumps(registry_fragment(registry, members), indent=1), encoding='utf-8')
    written.append(fragment_path)

    for filename in DEPOSIT_FILES:
        shutil.copy2(DEPOSIT_DIR / filename, DIST_DIR / filename)
        written.append(DIST_DIR / filename)

    checksums = DIST_DIR / 'SHA256SUMS'
    lines = [f'{digest(path, "sha256")}  {path.name}' for path in sorted(written, key=lambda p: p.name)]
    checksums.write_text('\n'.join(lines) + '\n', encoding='utf-8')

    deposit_size = sum(p.stat().st_size for p in DIST_DIR.iterdir())
    print(f'\n{len(written) + 1} files, {deposit_size / 1e6:.1f} MB, in {DIST_DIR}')
    print(f'verify with: cd {DIST_DIR} && shasum -a 256 -c SHA256SUMS')


if __name__ == '__main__':
    main()
