"""Reproducible archives."""

from __future__ import annotations

import gzip
import hashlib
import os
import tarfile
import time

import pytest

from research_helpers.archive import (
    EPOCH,
    archive_directory,
    digest,
    normalise,
    write_archive,
    write_checksums,
)


@pytest.fixture
def deposit(tmp_path):
    """Return a directory of files to archive."""
    root = tmp_path / 'deposit'
    (root / 'models').mkdir(parents=True)
    (root / 'README.md').write_text('A deposit.\n', encoding='utf-8')
    (root / 'models' / 'a.pt').write_bytes(b'weights a')
    (root / 'models' / 'b.pt').write_bytes(b'weights b')
    return root


# --- reproducibility --------------------------------------------------------------------------


def test_the_same_contents_give_the_same_bytes(deposit, tmp_path):
    first = archive_directory(tmp_path / 'first.tar.gz', deposit)

    # a later build, with the source files touched as a fresh checkout would leave them
    time.sleep(0.01)
    for path in deposit.rglob('*'):
        os.utime(path, None)
    second = archive_directory(tmp_path / 'second.tar.gz', deposit)

    assert first.read_bytes() == second.read_bytes()


def test_changed_contents_give_different_bytes(deposit, tmp_path):
    first = archive_directory(tmp_path / 'first.tar.gz', deposit)
    (deposit / 'models' / 'a.pt').write_bytes(b'weights a, revised')
    second = archive_directory(tmp_path / 'second.tar.gz', deposit)

    assert first.read_bytes() != second.read_bytes()


def test_the_order_members_are_given_in_does_not_matter(tmp_path, deposit):
    members = {
        'README.md': deposit / 'README.md',
        'models/a.pt': deposit / 'models' / 'a.pt',
    }
    forwards = write_archive(tmp_path / 'forwards.tar.gz', members)
    backwards = write_archive(tmp_path / 'backwards.tar.gz', dict(reversed(list(members.items()))))

    assert forwards.read_bytes() == backwards.read_bytes()


def test_the_gzip_header_carries_no_name_or_timestamp(deposit, tmp_path):
    archive = archive_directory(tmp_path / 'deposit.tar.gz', deposit)

    header = archive.read_bytes()[:10]
    flags, stamp = header[3], int.from_bytes(header[4:8], 'little')

    assert stamp == EPOCH
    assert not flags & 0x08, 'FNAME is set, so the source filename is embedded'


# --- member metadata --------------------------------------------------------------------------


def test_host_specific_metadata_is_stripped(deposit, tmp_path):
    archive = archive_directory(tmp_path / 'deposit.tar.gz', deposit)

    with tarfile.open(archive) as tar:
        members = tar.getmembers()

    assert members, 'the archive is empty'
    for member in members:
        assert member.mtime == EPOCH
        assert member.uid == member.gid == 0
        assert member.uname == member.gname == ''
        assert member.mode == 0o644


def test_an_executable_bit_does_not_survive(deposit, tmp_path):
    script = deposit / 'run.sh'
    script.write_text('#!/bin/sh\n', encoding='utf-8')
    script.chmod(0o755)

    archive = archive_directory(tmp_path / 'deposit.tar.gz', deposit)

    with tarfile.open(archive) as tar:
        assert tar.getmember('run.sh').mode == 0o644


def test_a_directory_keeps_a_traversable_mode():
    info = tarfile.TarInfo('models')
    info.type = tarfile.DIRTYPE

    assert normalise(info).mode == 0o755


def test_the_timestamp_can_be_pinned_to_something_else(deposit, tmp_path):
    archive = archive_directory(tmp_path / 'deposit.tar.gz', deposit, mtime=1600000000)

    with tarfile.open(archive) as tar:
        assert tar.getmembers()[0].mtime == 1600000000
    with gzip.open(archive) as handle:
        assert handle.read()


# --- contents ---------------------------------------------------------------------------------


def test_every_file_is_stored_under_its_path_relative_to_the_source(deposit, tmp_path):
    archive = archive_directory(tmp_path / 'deposit.tar.gz', deposit)

    with tarfile.open(archive) as tar:
        assert set(tar.getnames()) == {'README.md', 'models/a.pt', 'models/b.pt'}


def test_members_can_be_stored_under_names_of_the_callers_choosing(deposit, tmp_path):
    archive = write_archive(
        tmp_path / 'deposit.tar.gz',
        {'la/pos/model.pt': deposit / 'models' / 'a.pt'},
    )

    with tarfile.open(archive) as tar:
        assert tar.getnames() == ['la/pos/model.pt']
        stored = tar.extractfile('la/pos/model.pt')
        assert stored is not None
        assert stored.read() == b'weights a'


def test_the_parent_directory_is_created(deposit, tmp_path):
    archive = archive_directory(tmp_path / 'nested' / 'dir' / 'deposit.tar.gz', deposit)

    assert archive.exists()


# --- digests and checksum files -----------------------------------------------------------------


def test_digest_matches_hashlib(deposit):
    path = deposit / 'README.md'

    assert digest(path) == hashlib.sha256(path.read_bytes()).hexdigest()


def test_digest_takes_another_algorithm(deposit):
    path = deposit / 'README.md'

    assert digest(path, 'md5') == hashlib.md5(path.read_bytes()).hexdigest()


def test_a_file_larger_than_one_block_hashes_correctly(tmp_path):
    path = tmp_path / 'big.bin'
    payload = b'x' * (3 * (1 << 20) + 17)
    path.write_bytes(payload)

    assert digest(path) == hashlib.sha256(payload).hexdigest()


def test_the_checksum_file_is_in_the_format_shasum_reads(deposit):
    paths = [deposit / 'README.md', deposit / 'models' / 'a.pt']

    sums = write_checksums(paths, deposit / 'SHA256SUMS')

    lines = sums.read_text(encoding='utf-8').splitlines()
    assert lines == [
        f'{digest(deposit / "README.md")}  README.md',
        f'{digest(deposit / "models" / "a.pt")}  models/a.pt',
    ]


def test_the_checksum_file_is_verified_by_shasum(deposit):
    """The point of the format is that the standard tool reads it."""
    import shutil
    import subprocess

    if not shutil.which('shasum'):
        # `ty` resolves pytest's @_with_exception-decorated `skip` as taking no arguments, so
        # it rejects the reason either positionally or by keyword. The call is correct.
        pytest.skip('shasum is not available')  # ty: ignore[too-many-positional-arguments]

    write_checksums([deposit / 'README.md', deposit / 'models' / 'a.pt'], deposit / 'SHA256SUMS')
    result = subprocess.run(
        ['shasum', '-a', '256', '-c', 'SHA256SUMS'],
        cwd=deposit,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr


def test_the_checksum_file_is_deterministic(deposit):
    paths = list(deposit.rglob('*.pt'))

    first = write_checksums(paths, deposit / 'A').read_text(encoding='utf-8')
    second = write_checksums(list(reversed(paths)), deposit / 'B').read_text(encoding='utf-8')

    assert first == second
