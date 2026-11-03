import importlib
import logging
import sys
from collections.abc import Iterator
from types import ModuleType

import pytest
from flask.testing import FlaskClient

from household import _UnprocessedEmailsError

_TOKEN = '{"refresh_token": "test"}'


class _FakeHousehold:
    def __init__(self) -> None:
        self.confirmed_services: list[str] = []
        self.renewed: list[tuple[str, str]] = []
        self.confirm_error: Exception | None = None

    def build_gmail_service(self, token_json: str) -> str:
        return f"service({token_json})"

    def confirm_household_emails(self, service: str) -> None:
        self.confirmed_services.append(service)
        if self.confirm_error is not None:
            raise self.confirm_error

    def renew_watch(self, service: str, topic_name: str) -> None:
        self.renewed.append((service, topic_name))


@pytest.fixture
def environment(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("PROJECT_ID", "test-project")
    monkeypatch.setenv("TOPIC_ID", "gmail-netflix")
    monkeypatch.setenv("GMAIL_TOKEN", _TOKEN)
    root = logging.getLogger()
    handlers, level = root.handlers[:], root.level
    sys.modules.pop("main", None)
    yield
    sys.modules.pop("main", None)
    root.handlers, root.level = handlers, level


@pytest.fixture
def main_module(environment: None) -> ModuleType:
    return importlib.import_module("main")


@pytest.fixture
def household(main_module: ModuleType, monkeypatch: pytest.MonkeyPatch) -> _FakeHousehold:
    fake = _FakeHousehold()
    for name in ("build_gmail_service", "confirm_household_emails", "renew_watch"):
        monkeypatch.setattr(main_module, name, getattr(fake, name))
    return fake


@pytest.fixture
def client(main_module: ModuleType, household: _FakeHousehold) -> FlaskClient:
    test_client: FlaskClient = main_module.app.test_client()
    return test_client


def test_pubsub_returns_204_when_all_emails_are_processed(
    client: FlaskClient, household: _FakeHousehold
) -> None:
    response = client.post("/pubsub", json={"message": {"data": "e30="}})

    assert response.status_code == 204
    assert household.confirmed_services == [f"service({_TOKEN})"]


def test_pubsub_returns_500_when_emails_remain(
    client: FlaskClient, household: _FakeHousehold
) -> None:
    household.confirm_error = _UnprocessedEmailsError(["m1"])

    response = client.post("/pubsub")

    assert response.status_code == 500


def test_renew_passes_full_topic_name(client: FlaskClient, household: _FakeHousehold) -> None:
    response = client.post("/renew")

    assert response.status_code == 200
    assert household.renewed == [
        (f"service({_TOKEN})", "projects/test-project/topics/gmail-netflix")
    ]


@pytest.mark.parametrize("path", ["/pubsub", "/renew"])
def test_get_is_not_allowed(client: FlaskClient, path: str) -> None:
    assert client.get(path).status_code == 405


@pytest.mark.usefixtures("environment")
def test_missing_environment_variable_fails_at_startup(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GMAIL_TOKEN")

    with pytest.raises(KeyError, match="GMAIL_TOKEN"):
        importlib.import_module("main")
