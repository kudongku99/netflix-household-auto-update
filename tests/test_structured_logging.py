import json
import logging
from collections.abc import Iterator
from typing import Any

import pytest

from structured_logging import configure_logging

_CLOUD_LOGGING_SEVERITIES = {
    "DEFAULT",
    "DEBUG",
    "INFO",
    "NOTICE",
    "WARNING",
    "ERROR",
    "CRITICAL",
    "ALERT",
    "EMERGENCY",
}


@pytest.fixture(autouse=True)
def _restore_root_logger() -> Iterator[None]:
    root = logging.getLogger()
    handlers, level = root.handlers[:], root.level
    yield
    root.handlers, root.level = handlers, level


def _read_lines(capsys: pytest.CaptureFixture[str]) -> list[dict[str, Any]]:
    lines = capsys.readouterr().out.splitlines()
    return [json.loads(line) for line in lines]


def test_message_is_written_as_one_json_line(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging()

    logging.getLogger("household").info("확인 완료: %s", "메일 1통")

    assert _read_lines(capsys) == [{"severity": "INFO", "message": "확인 완료: 메일 1통"}]


def test_korean_is_not_escaped(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging()

    logging.getLogger().warning("만료되어 건너뜀")

    assert "만료되어 건너뜀" in capsys.readouterr().out


def test_exception_traceback_is_included_in_one_line(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging()

    try:
        raise ValueError("페이지 로드 시간 초과")
    except ValueError:
        logging.getLogger().exception("메일 처리 중 오류")

    [entry] = _read_lines(capsys)
    assert entry["severity"] == "ERROR"
    assert entry["message"].startswith("메일 처리 중 오류\nTraceback")
    assert "ValueError: 페이지 로드 시간 초과" in entry["message"]


@pytest.mark.parametrize(
    "level", [logging.DEBUG, logging.INFO, logging.WARNING, logging.ERROR, logging.CRITICAL]
)
def test_severity_matches_cloud_logging(capsys: pytest.CaptureFixture[str], level: int) -> None:
    configure_logging(logging.DEBUG)

    logging.getLogger().log(level, "message")

    [entry] = _read_lines(capsys)
    assert entry["severity"] == logging.getLevelName(level)
    assert entry["severity"] in _CLOUD_LOGGING_SEVERITIES


def test_messages_below_level_are_dropped(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging()

    logging.getLogger().debug("hidden")

    assert capsys.readouterr().out == ""


def test_configuring_twice_does_not_duplicate_output(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging()
    configure_logging()

    logging.getLogger().info("once")

    assert len(_read_lines(capsys)) == 1
