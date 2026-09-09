"""Logging."""

from __future__ import annotations

import io
import logging
import threading

import pytest
import structlog

from research_helpers.log import (
    LoggingTqdm,
    get_logger,
    progress,
    reset_logging,
    set_log_file,
    setup_logging,
)
from research_helpers.project import _load


class Terminal(io.StringIO):
    """A stream that claims to be a terminal, so colour decisions can be exercised."""

    def isatty(self) -> bool:
        """Report that this is a terminal."""
        return True


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path):
    """Put the root logger back exactly as it was found. Logging is process-global."""
    monkeypatch.delenv('RESEARCH_HELPERS_ROOT', raising=False)
    _load.cache_clear()
    root = logging.getLogger()
    handlers, level = list(root.handlers), root.level
    workdir = tmp_path / 'nowhere'
    workdir.mkdir()
    monkeypatch.chdir(workdir)
    yield
    reset_logging()
    root.handlers[:] = handlers
    root.setLevel(level)
    structlog.reset_defaults()
    _load.cache_clear()


@pytest.fixture
def console():
    """Return a console stream that logging is configured to write to."""
    stream = io.StringIO()
    setup_logging(stream=stream, colour='never')
    return stream


# --- configuration and reconfiguration ----------------------------------------------------------


def test_get_logger_configures_logging_when_nothing_has():
    stream = io.StringIO()
    setup_logging(stream=stream, colour='never')
    get_logger('demo').info('hello')

    assert 'hello' in stream.getvalue()


def test_get_logger_does_not_reconfigure_once_configured(tmp_path):
    setup_logging(directory=tmp_path / 'logs', stream=io.StringIO())
    installed = list(logging.getLogger().handlers)

    get_logger('one')
    get_logger('two')

    assert list(logging.getLogger().handlers) == installed


def test_an_explicit_setup_wins_over_one_a_logger_triggered(tmp_path):
    """main() must still be able to configure."""
    get_logger('imported.at.module.level')  # implicitly configures, with no file logging

    setup_logging(directory=tmp_path / 'logs', stream=io.StringIO())
    get_logger('later').info('written to file')

    assert (tmp_path / 'logs' / 'app.log').read_text(encoding='utf-8').strip().endswith('written to file')


def test_reconfiguring_does_not_accumulate_handlers(tmp_path):
    before = list(logging.getLogger().handlers)

    setup_logging(stream=io.StringIO())
    setup_logging(stream=io.StringIO())
    setup_logging(directory=tmp_path / 'logs', stream=io.StringIO())

    added = [handler for handler in logging.getLogger().handlers if handler not in before]

    assert len(added) == 2, 'one console handler and one file handler, however often setup runs'


def test_reset_removes_what_setup_installed(tmp_path):
    before = list(logging.getLogger().handlers)
    setup_logging(directory=tmp_path / 'logs', stream=io.StringIO())
    assert len(logging.getLogger().handlers) == len(before) + 2

    reset_logging()

    assert logging.getLogger().handlers == before


# --- what used to break -------------------------------------------------------------------------


def test_a_worker_thread_does_not_disturb_the_root_handlers(tmp_path):
    """Config state is process-global."""
    setup_logging(directory=tmp_path / 'logs', stream=io.StringIO())
    before = list(logging.getLogger().handlers)
    seen: dict[str, list[logging.Handler]] = {}

    def worker() -> None:
        get_logger('worker').info('from a thread')
        seen['after'] = list(logging.getLogger().handlers)

    thread = threading.Thread(target=worker)
    thread.start()
    thread.join()

    assert seen['after'] == before
    assert 'from a thread' in (tmp_path / 'logs' / 'app.log').read_text(encoding='utf-8')


def test_handlers_installed_by_anything_else_survive():
    other = logging.Handler()
    logging.getLogger().addHandler(other)

    setup_logging(stream=io.StringIO())

    assert other in logging.getLogger().handlers


def test_pytest_can_still_capture_logs(caplog):
    with caplog.at_level(logging.INFO):
        setup_logging(stream=io.StringIO())
        get_logger('demo').info('captured')

    assert 'captured' in caplog.text


def test_the_root_level_is_lowered_even_when_logging_was_configured_first(tmp_path):
    """basicConfig() does nothing once anything has configured logging. So the level was left high."""
    logging.getLogger().addHandler(logging.NullHandler())
    logging.getLogger().setLevel(logging.WARNING)

    setup_logging(directory=tmp_path / 'logs', file_level='DEBUG', stream=io.StringIO())

    assert logging.getLogger().level == logging.DEBUG


def test_a_debug_record_reaches_the_file_while_the_console_stays_quiet(tmp_path):
    stream = io.StringIO()
    setup_logging(directory=tmp_path / 'logs', console_level='INFO', file_level='DEBUG', stream=stream)

    get_logger('demo').debug('a detail')

    assert 'a detail' not in stream.getvalue()
    assert 'a detail' in (tmp_path / 'logs' / 'app.log').read_text(encoding='utf-8')


def test_the_logger_name_is_shown_rather_than_unknown(console):
    get_logger('research_helpers.demo').info('hello')

    output = console.getvalue()

    assert 'research_helpers.demo hello' in output
    assert 'unknown' not in output
    assert 'logger=' not in output, 'the name is shown once, not also in the context'


def test_a_traceback_is_written_below_the_line_not_inside_the_context(console):
    try:
        1 / 0
    except ZeroDivisionError:
        get_logger('demo').exception('extraction failed', document='ms-4021')

    first, _, rest = console.getvalue().partition('\n')

    assert 'extraction failed' in first
    assert 'document=ms-4021' in first
    assert 'exception=' not in first, 'the traceback used to be packed into the context'
    assert rest.startswith('Traceback (most recent call last):')
    assert 'ZeroDivisionError: division by zero' in rest


# --- colour ---------------------------------------------------------------------------------------


def test_colour_is_used_on_a_terminal():
    stream = Terminal()
    setup_logging(stream=stream, colour='auto')

    get_logger('demo').info('hello')

    assert '\x1b[' in stream.getvalue()


def test_colour_is_withheld_when_output_is_redirected():
    stream = io.StringIO()
    setup_logging(stream=stream, colour='auto')

    get_logger('demo').info('hello')

    assert '\x1b[' not in stream.getvalue()


def test_colour_can_be_forced_on_and_off():
    forced = io.StringIO()
    setup_logging(stream=forced, colour='always')
    get_logger('demo').info('hello')

    suppressed = Terminal()
    setup_logging(stream=suppressed, colour='never')
    get_logger('demo').info('hello')

    assert '\x1b[' in forced.getvalue()
    assert '\x1b[' not in suppressed.getvalue()


def test_importing_the_module_does_not_replace_stdout():
    import sys

    import research_helpers.log.formatters

    assert type(sys.stdout).__name__ != 'StreamWrapper', 'colorama used to wrap stdout on import'
    assert research_helpers.log.formatters.Renderer


# --- levels ---------------------------------------------------------------------------------------


def test_a_name_that_is_not_a_level_is_rejected_clearly():
    with pytest.raises(ValueError, match='not a logging level'):
        setup_logging(console_level='TRACE', stream=io.StringIO())


def test_a_level_can_be_given_as_an_int():
    stream = io.StringIO()
    setup_logging(console_level=logging.WARNING, stream=stream)

    get_logger('demo').info('quiet')
    get_logger('demo').warning('loud')

    assert 'quiet' not in stream.getvalue()
    assert 'loud' in stream.getvalue()


# --- files ------------------------------------------------------------------------------------------


def test_records_go_to_the_file_their_logger_is_mapped_to(tmp_path):
    setup_logging(directory=tmp_path / 'logs', stream=io.StringIO())
    set_log_file('extraction', 'extraction.log')

    get_logger('extraction').info('an extracted entity')
    get_logger('elsewhere').info('something else')

    assert 'an extracted entity' in (tmp_path / 'logs' / 'extraction.log').read_text(encoding='utf-8')
    assert 'something else' in (tmp_path / 'logs' / 'app.log').read_text(encoding='utf-8')


def test_set_log_file_returns_where_records_will_go(tmp_path):
    setup_logging(directory=tmp_path / 'logs', stream=io.StringIO())

    assert set_log_file('extraction', 'extraction.log') == tmp_path / 'logs' / 'extraction.log'


def test_set_log_file_without_a_log_directory_says_so():
    setup_logging(stream=io.StringIO())

    with pytest.raises(RuntimeError, match='no log directory is configured'):
        set_log_file('extraction', 'extraction.log')


def test_the_default_log_is_not_created_until_something_writes_to_it(tmp_path):
    setup_logging(directory=tmp_path / 'logs', stream=io.StringIO())

    assert (tmp_path / 'logs').is_dir()
    assert not (tmp_path / 'logs' / 'app.log').exists()


def test_the_file_carries_the_full_timestamp_and_the_console_only_the_time(tmp_path):
    stream = io.StringIO()
    setup_logging(directory=tmp_path / 'logs', stream=stream, colour='never')

    get_logger('demo').info('hello')

    # a line reads '[LEVEL   ] <timestamp> <module> <event>', the level itself contains spaces
    written = (tmp_path / 'logs' / 'app.log').read_text(encoding='utf-8').split('] ', 1)[1]
    shown = stream.getvalue().split('] ', 1)[1]

    assert 'T' in written.split()[0], 'the file keeps the date'
    assert 'T' not in shown.split()[0]
    assert shown.split()[0].count(':') == 2, 'the console shows a clock time'


# --- settings -------------------------------------------------------------------------------------


def test_settings_come_from_the_project(tmp_path, monkeypatch):
    root = tmp_path / 'project'
    root.mkdir()
    (root / 'pyproject.toml').write_text(
        '[tool.research-helpers.log]\ndirectory = "var/logs"\nconsole-level = "WARNING"\ncolour = "never"\n',
        encoding='utf-8',
    )
    monkeypatch.chdir(root)
    _load.cache_clear()

    stream = io.StringIO()
    setup_logging(stream=stream)
    get_logger('demo').info('quiet')
    get_logger('demo').error('loud')

    assert 'quiet' not in stream.getvalue()
    assert 'loud' in stream.getvalue()
    assert (root / 'var' / 'logs' / 'app.log').exists()


def test_arguments_override_the_project(tmp_path, monkeypatch):
    root = tmp_path / 'project'
    root.mkdir()
    (root / 'pyproject.toml').write_text(
        '[tool.research-helpers.log]\nconsole-level = "WARNING"\n',
        encoding='utf-8',
    )
    monkeypatch.chdir(root)
    _load.cache_clear()

    stream = io.StringIO()
    setup_logging(console_level='INFO', stream=stream, colour='never')
    get_logger('demo').info('now audible')

    assert 'now audible' in stream.getvalue()


# --- progress bars ----------------------------------------------------------------------------------


def test_progress_routes_log_output_around_the_bar(console):
    bar = io.StringIO()

    with progress():
        for _ in LoggingTqdm(range(2), file=bar, disable=False):
            get_logger('demo').info('a step')

    assert console.getvalue().count('a step') == 2
