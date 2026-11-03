from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow

_SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]
_PROJECT_DIRECTORY = Path(__file__).parent
_CREDENTIALS_PATH = _PROJECT_DIRECTORY / "credentials.json"
_TOKEN_PATH = _PROJECT_DIRECTORY / "token.json"


def main() -> None:
    if not _CREDENTIALS_PATH.exists():
        raise SystemExit(
            f"{_CREDENTIALS_PATH}가 없습니다. OAuth 클라이언트 JSON을 이 이름으로 두세요."
        )

    flow = InstalledAppFlow.from_client_secrets_file(str(_CREDENTIALS_PATH), _SCOPES)
    credentials = flow.run_local_server(port=0, prompt="consent", access_type="offline")
    if not credentials.refresh_token:
        raise SystemExit("리프레시 토큰을 받지 못했습니다. 다시 실행해 동의 화면에서 허용하세요.")

    _TOKEN_PATH.write_text(credentials.to_json())
    _TOKEN_PATH.chmod(0o600)
    print(f"{_TOKEN_PATH} 저장 완료")


if __name__ == "__main__":
    main()
