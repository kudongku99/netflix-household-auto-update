import os

from flask import Flask

from household import (
    _UnprocessedEmailsError,
    build_gmail_service,
    confirm_household_emails,
    renew_watch,
)
from structured_logging import configure_logging

configure_logging()

PROJECT_ID = os.environ["PROJECT_ID"]
TOPIC_ID = os.environ["TOPIC_ID"]
GMAIL_TOKEN = os.environ["GMAIL_TOKEN"]
TOPIC_NAME = f"projects/{PROJECT_ID}/topics/{TOPIC_ID}"

app = Flask(__name__)


@app.post("/pubsub")
def pubsub() -> tuple[str, int]:
    try:
        confirm_household_emails(build_gmail_service(GMAIL_TOKEN))
    except _UnprocessedEmailsError:
        return "", 500
    return "", 204


@app.post("/renew")
def renew() -> tuple[str, int]:
    renew_watch(build_gmail_service(GMAIL_TOKEN), TOPIC_NAME)
    return "", 200
