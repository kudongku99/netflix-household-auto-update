import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from household import (
    _AFTER_CLICK_TIMEOUT,
    _BUTTON_WAIT_TIMEOUT,
    _MAX_AGE,
    _PAGE_LOAD_TIMEOUT,
    _REQUEST_TIMEOUT,
    _WORST_CASE_EMAIL_DURATION,
    _is_expired,
)

_NOW = datetime(2026, 10, 23, 15, 0, tzinfo=UTC)
_PROJECT_ROOT = Path(__file__).parent.parent


@pytest.mark.parametrize(
    ("age", "expected"),
    [
        (timedelta(0), False),
        (timedelta(minutes=14, seconds=59), False),
        (_MAX_AGE, False),
        (_MAX_AGE + timedelta(seconds=1), True),
        (timedelta(hours=1), True),
    ],
)
def test_is_expired(age: timedelta, expected: bool) -> None:
    assert _is_expired(_NOW - age, _NOW) is expected


def test_max_age_matches_link_lifetime() -> None:
    assert timedelta(minutes=15) == _MAX_AGE


def test_worst_case_email_duration_is_timeouts_plus_margin() -> None:
    timeouts = _PAGE_LOAD_TIMEOUT + _BUTTON_WAIT_TIMEOUT + _AFTER_CLICK_TIMEOUT
    assert timeouts + timedelta(seconds=15) == _WORST_CASE_EMAIL_DURATION
    assert timedelta(seconds=100) == _WORST_CASE_EMAIL_DURATION


def test_worst_case_email_fits_in_request_timeout() -> None:
    assert _WORST_CASE_EMAIL_DURATION <= _REQUEST_TIMEOUT
    assert timedelta(seconds=120) == _REQUEST_TIMEOUT


def test_dockerfile_gunicorn_timeout_matches_request_timeout() -> None:
    dockerfile = (_PROJECT_ROOT / "Dockerfile").read_text()

    timeouts = re.findall(r"--timeout (\d+)", dockerfile)

    assert timeouts == [str(int(_REQUEST_TIMEOUT.total_seconds()))]


@pytest.mark.parametrize("option", ["--timeout", "--ack-deadline"])
def test_deploy_script_timeout_matches_request_timeout(option: str) -> None:
    deploy_script = (_PROJECT_ROOT / "deploy.sh").read_text()

    values = re.findall(rf"{option}[ =](\d+)", deploy_script)

    assert values == [str(int(_REQUEST_TIMEOUT.total_seconds()))]
