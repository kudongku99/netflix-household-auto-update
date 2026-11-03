import base64
import logging
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from typing import Any
from unittest.mock import MagicMock

import pytest

import household
from household import _UnprocessedEmailsError, confirm_household_emails

_BUTTON_URL = "https://www.netflix.com/account/update-primary-location?nftoken=test"


def _raw_email(html: str) -> str:
    message = EmailMessage()
    message["From"] = "Netflix <info@account.netflix.com>"
    message["Subject"] = "test"
    message.set_content("plain text")
    message.add_alternative(html, subtype="html")
    return base64.urlsafe_b64encode(message.as_bytes()).decode()


def _gmail_message(
    *, age: timedelta = timedelta(minutes=1), url: str | None = _BUTTON_URL
) -> dict[str, str]:
    html = f'<a href="{url}">네, 본인입니다</a>' if url else "<p>no button</p>"
    received_at = datetime.now(UTC) - age
    return {
        "internalDate": str(int(received_at.timestamp() * 1000)),
        "raw": _raw_email(html),
    }


def _fake_service(messages: dict[str, dict[str, str]]) -> MagicMock:
    service = MagicMock()
    messages_api = service.users.return_value.messages.return_value
    messages_api.list.return_value.execute.return_value = {
        "messages": [{"id": message_id} for message_id in messages]
    }

    def get(**parameters: str) -> MagicMock:
        request = MagicMock()
        request.execute.return_value = messages[parameters["id"]]
        return request

    messages_api.get.side_effect = get
    return service


def _read_ids(service: MagicMock) -> list[str]:
    modify = service.users.return_value.messages.return_value.modify
    for call in modify.call_args_list:
        assert call.kwargs["body"] == {"removeLabelIds": ["UNREAD"]}
    return [call.kwargs["id"] for call in modify.call_args_list]


class _FakeClicker:
    def __init__(self, results: dict[str, bool | Exception] | None = None) -> None:
        self.results = results or {}
        self.clicked_urls: list[str] = []

    def __call__(self, url: str) -> bool:
        self.clicked_urls.append(url)
        result = self.results.get(url, True)
        if isinstance(result, Exception):
            raise result
        return result


@pytest.fixture
def clicker(monkeypatch: pytest.MonkeyPatch) -> _FakeClicker:
    fake = _FakeClicker()
    monkeypatch.setattr(household, "_click_confirm_button", fake)
    return fake


def _messages_logged(caplog: pytest.LogCaptureFixture) -> list[tuple[int, str]]:
    return [(record.levelno, record.getMessage()) for record in caplog.records]


def test_no_email_does_nothing(clicker: _FakeClicker) -> None:
    service = _fake_service({})

    confirm_household_emails(service)

    assert clicker.clicked_urls == []
    assert _read_ids(service) == []


def test_confirmed_email_is_marked_read(
    clicker: _FakeClicker, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO)
    service = _fake_service({"m1": _gmail_message()})

    confirm_household_emails(service)

    assert clicker.clicked_urls == [_BUTTON_URL]
    assert _read_ids(service) == ["m1"]
    assert any(message.startswith("확인 완료: m1") for _, message in _messages_logged(caplog))


def test_expired_email_is_skipped(clicker: _FakeClicker, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)
    service = _fake_service({"m1": _gmail_message(age=timedelta(minutes=16))})

    confirm_household_emails(service)

    assert clicker.clicked_urls == []
    assert _read_ids(service) == []
    assert any(message.startswith("만료되어 건너뜀: m1") for _, message in _messages_logged(caplog))


def test_email_without_button_is_skipped(
    clicker: _FakeClicker, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO)
    service = _fake_service({"m1": _gmail_message(url=None)})

    confirm_household_emails(service)

    assert clicker.clicked_urls == []
    assert _read_ids(service) == []
    assert (logging.INFO, "확인 링크 없음: m1") in _messages_logged(caplog)


def test_button_not_found_keeps_email_unread_without_error(clicker: _FakeClicker) -> None:
    clicker.results[_BUTTON_URL] = False
    service = _fake_service({"m1": _gmail_message()})

    confirm_household_emails(service)

    assert clicker.clicked_urls == [_BUTTON_URL]
    assert _read_ids(service) == []


def test_error_in_one_email_does_not_block_others(
    clicker: _FakeClicker, caplog: pytest.LogCaptureFixture
) -> None:
    failing_url = "https://www.netflix.com/account/update-primary-location?nftoken=failing"
    clicker.results[failing_url] = RuntimeError("페이지 로드 시간 초과")
    service = _fake_service({"m1": _gmail_message(url=failing_url), "m2": _gmail_message()})

    with pytest.raises(_UnprocessedEmailsError) as raised:
        confirm_household_emails(service)

    assert raised.value.message_ids == ["m1"]
    assert clicker.clicked_urls == [failing_url, _BUTTON_URL]
    assert _read_ids(service) == ["m2"]
    assert (logging.ERROR, "메일 처리 중 오류: m1") in _messages_logged(caplog)


def test_remaining_emails_are_deferred_when_time_runs_short(
    clicker: _FakeClicker, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    times: Iterator[float] = iter([0.0, 0.0, 30.0])
    monkeypatch.setattr(household, "monotonic", lambda: next(times))
    service = _fake_service(
        {"m1": _gmail_message(), "m2": _gmail_message(), "m3": _gmail_message()}
    )

    with pytest.raises(_UnprocessedEmailsError) as raised:
        confirm_household_emails(service)

    assert raised.value.message_ids == ["m2", "m3"]
    assert clicker.clicked_urls == [_BUTTON_URL]
    assert _read_ids(service) == ["m1"]
    assert any(
        level == logging.WARNING
        and message.startswith("요청 제한 시간이 부족해 다음 알림으로 미룸")
        for level, message in _messages_logged(caplog)
    )


def test_gmail_query_targets_unread_netflix_mail(clicker: _FakeClicker) -> None:
    service = _fake_service({})

    confirm_household_emails(service)

    list_call: Any = service.users.return_value.messages.return_value.list.call_args
    assert list_call.kwargs == {"userId": "me", "q": "from:netflix.com is:unread newer_than:1d"}
