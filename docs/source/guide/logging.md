# Logging

{py:mod}`research_helpers.log` wires [structlog](https://www.structlog.org) onto the standard
library's logging to improve its capabilities and the quality of the output. It requires the `log` extra: 

```sh
pip install research-helpers[log]
```

## Setup

```python
from research_helpers.log import get_logger, setup_logging

setup_logging()
log = get_logger(__name__)

log.info('starting', corpus='perseus', sentences=18_000)
```

{py:func}`~research_helpers.log.setup_logging` takes its defaults from
`[tool.research-helpers.log]` and all can be overriden:

```python
setup_logging(console_level='DEBUG', directory='data/logs', colour='never')
```

It should be called once, at the entry point. Calling it again reconfigures rather than stacking handlers, 
so a notebook that re-runs its first cell does not end up printing everything twice.
{py:func}`~research_helpers.log.reset_logging` removes the handlers entirely.

## Console and file levels

Console and file get different levels—`INFO` and `DEBUG`—by default, in order to keep the console relatively quiet 
and readable while sending the detail to disk.

If `directory` is not set, there is no file and only the console is configured.

## Colour

The package's default for `colour` is `auto`, which colours output only when stderr is a terminal. 
If the output is redirected to a file or pipe, e.g., through `tee`, the escape codes are removed. 
`always` and `never` can be used to force a specific behaviour.

## Multiple concurrent log files

{py:func}`~research_helpers.log.set_log_file` routes one logger's output to its own file:

```python
set_log_file('bootstrapping.evaluation', 'evaluation.log')
```

Handlers are opened lazily, so declaring a file for a stage that never runs does not leave an
empty file behind.

## Progress bars

{py:func}`~research_helpers.log.progress` redirects logging around a `tqdm` bar for as long as 
it is on-screen:

```python
from research_helpers.log import progress, LoggingTqdm

with progress():
    for item in LoggingTqdm(items, desc='scoring'):
        log.info('scored', item=item.id)     # printed above the bar, not through it
```
