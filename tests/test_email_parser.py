import base64
from email.message import EmailMessage
from pathlib import Path

import pytest

from email_parser import decode_message, find_button_url

_FIXTURE = Path(__file__).parent / "fixtures" / "household_update_ko.eml"
_FIXTURE_BUTTON_URL = (
    "https://www.netflix.com/account/update-primary-location"
    "?nftoken=REDACTED&g=00000000-0000-0000-0000-000000000000"
    "&lnktrk=EVO&operation=update&lkid=UPDATE_HOUSEHOLD_REQUESTED_OTP_CTA"
)


def _encode_raw(content: bytes) -> str:
    return base64.urlsafe_b64encode(content).decode()


def _build_raw(html: str, transfer_encoding: str = "quoted-printable") -> str:
    message = EmailMessage()
    message["From"] = "Netflix <info@account.netflix.com>"
    message["To"] = "user@example.com"
    message["Subject"] = "test"
    message.set_content("plain text", charset="utf-8", cte=transfer_encoding)
    message.add_alternative(html, subtype="html", charset="utf-8", cte=transfer_encoding)
    return _encode_raw(message.as_bytes())


def test_fixture_button_url_is_extracted() -> None:
    message = decode_message(_encode_raw(_FIXTURE.read_bytes()))

    url = find_button_url(message)

    assert url == _FIXTURE_BUTTON_URL
    assert "&amp;" not in url


def test_fixture_headers_are_decoded() -> None:
    message = decode_message(_encode_raw(_FIXTURE.read_bytes()))

    assert message["From"] == "Netflix <info@account.netflix.com>"
    assert message["Subject"] == "중요: 넷플릭스 이용 가구를 업데이트하는 방법"


def test_raw_without_padding_is_decoded() -> None:
    raw = _build_raw('<a href="https://example.com/ok">네, 본인입니다</a>')
    assert raw.endswith("=")

    assert find_button_url(decode_message(raw.rstrip("="))) == "https://example.com/ok"


@pytest.mark.parametrize("transfer_encoding", ["quoted-printable", "base64"])
@pytest.mark.parametrize("button_text", ["네, 본인입니다", "Yes, This Was Me"])
def test_button_is_found_for_each_language_and_encoding(
    button_text: str, transfer_encoding: str
) -> None:
    html = f'<a href="https://example.com/ok?a=1&amp;b=2">{button_text}</a>'

    message = decode_message(_build_raw(html, transfer_encoding))

    assert find_button_url(message) == "https://example.com/ok?a=1&b=2"


def test_button_text_split_by_nested_tags_is_found() -> None:
    html = '<a href="https://example.com/ok"><span>네,</span>\n  <b>본인입니다</b></a>'

    assert find_button_url(decode_message(_build_raw(html))) == "https://example.com/ok"


def test_other_links_are_ignored() -> None:
    html = (
        '<a href="https://example.com/password">비밀번호 변경</a>'
        '<a href="https://example.com/ok">네, 본인입니다</a>'
    )

    assert find_button_url(decode_message(_build_raw(html))) == "https://example.com/ok"


def test_message_without_button_returns_none() -> None:
    html = '<a href="https://example.com/help">고객 센터</a>'

    assert find_button_url(decode_message(_build_raw(html))) is None


def test_plain_text_only_message_returns_none() -> None:
    message = EmailMessage()
    message.set_content("네, 본인입니다 https://example.com/ok")

    assert find_button_url(decode_message(_encode_raw(message.as_bytes()))) is None
