"""Byte-reproducible archives and checksums for data deposits and submissions."""

from __future__ import annotations

import gzip
import hashlib
import tarfile
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

__all__ = [
    'EPOCH',
    'archive_directory',
    'digest',
    'normalise',
    'write_archive',
    'write_checksums',
]

# the timestamp every member and the gzip header carry
# zero rather than 'now', so a rebuild of unchanged content produces an unchanged file
EPOCH = 0

DEFAULT_ALGORITHM = 'sha256'
DEFAULT_COMPRESS_LEVEL = 6

FILE_MODE = 0o644
DIRECTORY_MODE = 0o755

# 1 MB, so a large deposit is not read into memory to be hashed
BLOCK = 1 << 20


def digest(path: Path | str, algorithm: str = DEFAULT_ALGORITHM) -> str:
    """Return the hex digest of a file, read in blocks.

    Arguments:
        path: the file to hash.
        algorithm: any name 'hashlib.new' accepts.

    Returns:
        The digest, as hex.

    """
    hasher = hashlib.new(algorithm)
    with Path(path).open('rb') as handle:
        while block := handle.read(BLOCK):
            hasher.update(block)
    return hasher.hexdigest()


def normalise(info: tarfile.TarInfo, mtime: int = EPOCH) -> tarfile.TarInfo:
    """Strip host-specific metadata from an archive member.

    Arguments:
        info: the member to normalise, modified in place.
        mtime: the timestamp to record.

    Returns:
        The member.

    """
    info.mtime = mtime
    info.uid = info.gid = 0
    info.uname = info.gname = ''
    info.mode = DIRECTORY_MODE if info.isdir() else FILE_MODE
    return info


def write_archive(
    archive: Path | str,
    members: Mapping[str, Path | str],
    *,
    mtime: int = EPOCH,
    compress_level: int = DEFAULT_COMPRESS_LEVEL,
) -> Path:
    """Write a gzipped tar whose bytes depend only on its contents and member names.

    Arguments:
        archive: where to write.
        members: the path each file takes inside the archive, to the file on disk.
        mtime: the timestamp recorded for every member and in the gzip header.
        compress_level: pinned, since it changes the bytes.

    Returns:
        The archive written.

    """
    target = Path(archive)
    target.parent.mkdir(parents=True, exist_ok=True)

    with (
        target.open('wb') as raw,
        # filename='' keeps the source name out of the gzip header, mtime keeps the clock out
        gzip.GzipFile(filename='', mode='wb', compresslevel=compress_level, fileobj=raw, mtime=mtime) as compressed,
        # GNU_FORMAT rather than the default, which varies between Python versions
        tarfile.open(fileobj=compressed, mode='w', format=tarfile.GNU_FORMAT) as tar,
    ):
        for name in sorted(members):
            tar.add(Path(members[name]), arcname=name, filter=lambda info: normalise(info, mtime))
    return target


def archive_directory(
    archive: Path | str,
    source: Path | str,
    *,
    mtime: int = EPOCH,
    compress_level: int = DEFAULT_COMPRESS_LEVEL,
) -> Path:
    """Write every file under 'source' to a reproducible archive, named relative to it.

    Arguments:
        archive: where to write.
        source: the directory to pack.
        mtime: the timestamp recorded for every member and in the gzip header.
        compress_level: pinned, since it changes the bytes.

    Returns:
        The archive written.

    """
    directory = Path(source)
    members = {str(path.relative_to(directory)): path for path in directory.rglob('*') if path.is_file()}
    return write_archive(archive, members, mtime=mtime, compress_level=compress_level)


def write_checksums(
    paths: Iterable[Path | str],
    destination: Path | str,
    algorithm: str = DEFAULT_ALGORITHM,
) -> Path:
    """Write a checksum file in the format 'shasum -c' and 'sha256sum -c' read.

    Names are written relative to the checksum file, which is the directory a verifier runs in::

        cd dist && shasum -a 256 -c SHA256SUMS

    Arguments:
        paths: the files to record.
        destination: the checksum file to write, e.g. 'dist/SHA256SUMS'.
        algorithm: any name 'hashlib.new' accepts.

    Returns:
        The checksum file written.

    """
    target = Path(destination)
    base = target.parent
    entries = {}
    for item in paths:
        path = Path(item)
        name = str(path.relative_to(base)) if path.is_relative_to(base) else path.name
        entries[name] = digest(path, algorithm)

    target.parent.mkdir(parents=True, exist_ok=True)
    lines = [f'{entries[name]}  {name}' for name in sorted(entries)]
    target.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return target
