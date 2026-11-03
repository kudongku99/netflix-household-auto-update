import base64
from email import message_from_bytes, policy
from email.message import EmailMessage
from html.parser import HTMLParser

_BUTTON_TEXTS = ("네, 본인입니다", "Yes, This Was Me")


class _ButtonLinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._href: str | None = None
        self._text_parts: list[str] = []
        self.button_url: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "a":
            self._href = dict(attrs).get("href")
            self._text_parts = []

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._text_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag != "a" or self._href is None:
            return
        text = " ".join("".join(self._text_parts).split())
        if self.button_url is None and text in _BUTTON_TEXTS:
            self.button_url = self._href
        self._href = None


def decode_message(raw: str) -> EmailMessage:
    padded = raw + "=" * (-len(raw) % 4)
    return message_from_bytes(base64.urlsafe_b64decode(padded), policy=policy.default)


def find_button_url(message: EmailMessage) -> str | None:
    for part in message.walk():
        if part.get_content_type() != "text/html":
            continue
        parser = _ButtonLinkParser()
        parser.feed(part.get_content())
        parser.close()
        if parser.button_url is not None:
            return parser.button_url
    return None
