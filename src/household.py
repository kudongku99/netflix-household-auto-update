import json
import logging
from datetime import UTC, datetime, timedelta
from time import monotonic
from urllib.parse import urlsplit

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import Resource, build
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

from email_parser import decode_message, find_button_url

_logger = logging.getLogger(__name__)

_QUERY = "from:netflix.com is:unread newer_than:1d"
_MAX_AGE = timedelta(minutes=15)
_CONFIRM_SELECTOR = 'button[data-uia="set-primary-location-action"]'

_PAGE_LOAD_TIMEOUT = timedelta(seconds=45)
_BUTTON_WAIT_TIMEOUT = timedelta(seconds=20)
_AFTER_CLICK_TIMEOUT = timedelta(seconds=20)
_WORST_CASE_EMAIL_DURATION = (
    _PAGE_LOAD_TIMEOUT + _BUTTON_WAIT_TIMEOUT + _AFTER_CLICK_TIMEOUT + timedelta(seconds=15)
)
_REQUEST_TIMEOUT = timedelta(seconds=120)


class _UnprocessedEmailsError(Exception):
    def __init__(self, message_ids: list[str]) -> None:
        super().__init__(f"처리하지 못한 메일 {len(message_ids)}통: {', '.join(message_ids)}")
        self.message_ids = message_ids


def build_gmail_service(token_json: str) -> Resource:
    credentials = Credentials.from_authorized_user_info(json.loads(token_json))
    return build("gmail", "v1", credentials=credentials, cache_discovery=False)


def confirm_household_emails(service: Resource) -> None:
    started_at = monotonic()
    response = service.users().messages().list(userId="me", q=_QUERY).execute()
    message_ids: list[str] = [message["id"] for message in response.get("messages", [])]

    failed_ids: list[str] = []
    for index, message_id in enumerate(message_ids):
        elapsed = timedelta(seconds=monotonic() - started_at)
        if elapsed + _WORST_CASE_EMAIL_DURATION > _REQUEST_TIMEOUT:
            deferred_ids = message_ids[index:]
            _logger.warning(
                "요청 제한 시간이 부족해 다음 알림으로 미룸: %d통 (%s초 경과)",
                len(deferred_ids),
                int(elapsed.total_seconds()),
            )
            raise _UnprocessedEmailsError(failed_ids + deferred_ids)
        try:
            _confirm_email(service, message_id)
        except Exception:
            _logger.exception("메일 처리 중 오류: %s", message_id)
            failed_ids.append(message_id)

    if failed_ids:
        raise _UnprocessedEmailsError(failed_ids)


def renew_watch(service: Resource, topic_name: str) -> None:
    response = (
        service.users()
        .watch(userId="me", body={"topicName": topic_name, "labelIds": ["INBOX"]})
        .execute()
    )
    expires_at = datetime.fromtimestamp(int(response["expiration"]) / 1000, tz=UTC)
    _logger.info("watch 갱신 완료: %s 만료", expires_at.isoformat())


def _is_expired(received_at: datetime, now: datetime) -> bool:
    return now - received_at > _MAX_AGE


def _confirm_email(service: Resource, message_id: str) -> None:
    messages = service.users().messages()
    message = messages.get(userId="me", id=message_id, format="raw").execute()

    received_at = datetime.fromtimestamp(int(message["internalDate"]) / 1000, tz=UTC)
    now = datetime.now(UTC)
    if _is_expired(received_at, now):
        _logger.info(
            "만료되어 건너뜀: %s (받은 지 %d초)", message_id, (now - received_at).total_seconds()
        )
        return

    url = find_button_url(decode_message(message["raw"]))
    if url is None:
        _logger.info("확인 링크 없음: %s", message_id)
        return

    if not _click_confirm_button(url):
        return

    messages.modify(userId="me", id=message_id, body={"removeLabelIds": ["UNREAD"]}).execute()
    _logger.info("확인 완료: %s (받은 지 %d초)", message_id, (now - received_at).total_seconds())


def _click_confirm_button(url: str) -> bool:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(args=["--no-sandbox"])
        try:
            page = browser.new_page()
            page.goto(url, timeout=_milliseconds(_PAGE_LOAD_TIMEOUT))
            try:
                page.click(_CONFIRM_SELECTOR, timeout=_milliseconds(_BUTTON_WAIT_TIMEOUT))
            except PlaywrightTimeoutError:
                _logger.warning(
                    "확인 버튼을 찾지 못함: %s (제목: %s)", _without_query(page.url), page.title()
                )
                return False
            page.wait_for_load_state("networkidle", timeout=_milliseconds(_AFTER_CLICK_TIMEOUT))
            return True
        finally:
            browser.close()


def _milliseconds(duration: timedelta) -> float:
    return duration.total_seconds() * 1000


def _without_query(url: str) -> str:
    return urlsplit(url)._replace(query="", fragment="").geturl()
