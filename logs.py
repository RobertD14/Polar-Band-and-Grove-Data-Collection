"""System logging utilities."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING, Literal, get_args

import loguru
from loguru import logger

if TYPE_CHECKING:
    from io import TextIOWrapper

ROOT = Path(__file__).parent

LogLevel = Literal['TRACE', 'DEBUG', 'INFO', 'SUCCESS', 'WARNING', 'ERROR', 'CRITICAL']
LEVELS: tuple[LogLevel] = get_args(LogLevel)

LEVEL_COLOR: dict[LogLevel, str] = {
    'TRACE': '<magenta>',
    'DEBUG': '<cyan>',
    'INFO': '<black><bold>',
    'SUCCESS': '<green><bold>',
    'WARNING': '<yellow><bold>',
    'ERROR': '<red><bold>',
    'CRITICAL': '<RED><bold>',
}

LOGGER_FORMAT = (
    '<light-black>{time:YYYY-MM-DD HH:mm:ss.SSS}</light-black> | '
    '<level><bold>{level: >8}</bold></level> | '
    '<black>{extra[path]: >24}</black> | : '
    '<level>{message}</level>\n'
)


def configure_logger(level: LogLevel = 'INFO', file: loguru.Writable | TextIOWrapper | None = None) -> None:
    """Configure the logger with a specific level."""
    logger.remove()
    logger.configure(extra={'overwrite': False})
    logger.add(sys.stderr, level=level, format=_overwrite_stderr)
    if file:
        logger.add(file, level=level, format=formatter)

    for loglevel in LEVELS:
        logger.level(loglevel, color=LEVEL_COLOR[loglevel])


def formatter(record: loguru.Record) -> str:
    """Format the log message based on the level."""
    record['extra']['path'] = f'{Path(record["file"].path).relative_to(ROOT)}:{record["line"]}'
    if record['extra'].get('overwrite', False):
        return ''
    return LOGGER_FORMAT


def _overwrite_stderr(record: loguru.Record) -> str:
    """Format the log message for overwriting."""
    record['extra']['path'] = f'{Path(record["file"].path).relative_to(ROOT)}:{record["line"]}'
    format_ = '\033[F\033[K' if record['extra'].get('overwrite', False) else ''
    return format_ + LOGGER_FORMAT
