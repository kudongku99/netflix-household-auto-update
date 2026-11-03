# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 프로젝트 개요

넷플릭스 "이용가구 업데이트" 메일이 Gmail에 도착하면 몇 초 안에 확인 버튼을 대신 눌러주는 서버리스 서비스입니다. 사용자 기기가 꺼져 있어도 Google Cloud에서 동작합니다.

사람용 설정 절차와 문제 해결 표는 `README.md`에 있습니다.

## 배포 현황

GCP 프로젝트 `netflix-household-1027`(리전 `asia-northeast3`)에 2026-10-27 처음 배포했고, TV 요청으로 실제 확인 클릭까지 검증했습니다. Gmail 토큰은 넷플릭스 메일을 받는 계정으로 발급해 Secret `gmail-token`에 두었고, 로컬 `token.json`, `credentials.json`은 지웠습니다. gcloud 기본 프로젝트가 다른 프로젝트일 수 있으므로 명령에는 `--project`를 붙입니다.

## 아키텍처

단일 Cloud Run 서비스에 엔드포인트가 둘 있고, 두 개의 트리거 경로가 각각 하나씩을 호출합니다.

서비스 코드는 `src/`에 있고, 이미지에는 이 폴더 내용만 `/app` 바로 아래로 복사됩니다(그래서 gunicorn은 `main:app`, import는 `import household`). 코드는 네 파일로 나뉘고, import 방향은 `main` → `household` → `email_parser` 한쪽으로만 흐릅니다. `structured_logging`은 `main`만 import합니다.

- `src/main.py`: 환경변수를 읽고 Flask 라우팅만 합니다.
- `src/household.py`: 외부와 연결되는 로직(Gmail 조회, Playwright 클릭, watch 갱신)입니다. 토큰(`build_gmail_service`), Gmail 서비스 객체와 토픽 이름(`confirm_household_emails`, `renew_watch`)을 인자로 받고, 환경변수를 읽거나 Flask를 import하지 않습니다.
- `src/email_parser.py`: 메일 원문 디코딩과 버튼 링크 추출입니다. 표준 라이브러리만 씁니다.
- `src/structured_logging.py`: 루트 로거를 stdout JSON 한 줄(`severity`, `message`) 형식으로 설정합니다. Cloud Run이 이 형식을 구조화 로그로 읽어 심각도를 구분합니다. 표준 라이브러리만 씁니다. `google-cloud-logging`은 간접 의존성이 많아 쓰지 않았습니다.

이 경계를 유지합니다. 그래야 환경변수 없이 `household`를 import해 흐름을 테스트할 수 있고, `email_parser`는 외부 라이브러리 없이 테스트할 수 있습니다.

**알림 경로 (메일 도착 시)**

```
Gmail watch → Pub/Sub 토픽 gmail-netflix → push 구독(OIDC 인증)
→ Cloud Run POST /pubsub → household.confirm_household_emails()
```

`confirm_household_emails()`는 Pub/Sub 메시지 본문을 파싱하지 않습니다. 알림은 단순 트리거로만 쓰고, 실제 대상은 Gmail API 쿼리(`from:netflix.com is:unread newer_than:1d`)로 다시 찾습니다. 메일 원문(raw)에서 HTML 파트를 훑어 링크 텍스트가 `_BUTTON_TEXTS`("네, 본인입니다" / "Yes, This Was Me")와 일치하는 `<a href>`를 뽑고, Playwright 헤드리스 크로미움으로 열어 `_CONFIRM_SELECTOR`를 클릭합니다.

**watch 갱신 경로**

```
Cloud Scheduler gmail-watch-renew (매일 06:00 Asia/Seoul)
→ Cloud Run POST /renew → household.renew_watch() → users().watch()
```

Gmail watch는 7일이면 만료되므로 이 갱신이 멈추면 알림 경로 전체가 조용히 죽습니다. "아무 로그도 안 남는다"는 증상의 첫 번째 의심 지점입니다.

**중복 방지와 만료**

- 확인에 성공한 메일만 `UNREAD` 라벨을 제거합니다. 읽음 처리가 곧 처리 완료 표시이므로, 실패한 메일은 다음 알림 때 다시 시도됩니다.
- 메일 한 통에서 예외(페이지 로드 시간 초과, Gmail API 오류 등)가 나도 나머지 메일은 계속 처리합니다. 끝에서 `_UnprocessedEmailsError`를 올려 500을 반환하므로 Pub/Sub가 알림을 재전송합니다. 버튼을 찾지 못한 경우(`_click_confirm_button`이 `False`)는 재시도해도 같을 가능성이 높아 204로 끝냅니다.
- 메일 한 통의 최악 처리 시간(`_WORST_CASE_EMAIL_DURATION`, 페이지 로드·버튼 대기·클릭 후 대기 제한 시간 합 + 여유 15초 = 100초)이 요청 제한 시간(`_REQUEST_TIMEOUT`, 120초) 안에 남아 있지 않으면, 남은 메일은 처리하지 않고 같은 방식으로 500을 반환해 재전송에 맡깁니다. 제한 시간 도중에 gunicorn이 요청을 끊으면 어느 메일까지 처리됐는지 로그가 남지 않기 때문입니다.
- 요청 제한 시간 120초는 `_REQUEST_TIMEOUT`, `Dockerfile`의 gunicorn `--timeout`, `deploy.sh`의 Cloud Run `--timeout`과 Pub/Sub `--ack-deadline`, 아래 재배포 명령의 `--timeout`에 같은 값으로 들어 있습니다. 바꿀 때는 모두 함께 바꿉니다. 재배포 명령을 뺀 나머지는 `test_household.py`가 일치를 검사합니다. Playwright 제한 시간 상수를 늘려 최악 처리 시간이 요청 제한 시간을 넘으면 테스트가 실패합니다.
- 인증 링크는 15분 뒤 만료되므로 `_MAX_AGE`(15분)를 넘긴 메일은 건너뜁니다. 부팅이 지연돼 늦게 도착한 알림에서 만료된 링크를 여는 것을 막습니다.

**설정 주입**
`PROJECT_ID`, `TOPIC_ID`는 환경변수, Gmail OAuth 토큰은 Secret Manager의 `gmail-token`이 `GMAIL_TOKEN` 환경변수로 주입됩니다. 토큰은 파일이 아니라 JSON 문자열로 읽습니다(`Credentials.from_authorized_user_info`).

## 주요 명령

토큰 발급 (로컬에서 최초 1회):

```bash
.venv/bin/pip install google-auth-oauthlib
.venv/bin/python get_token.py
```

`get_token.py`는 프로젝트 폴더의 `credentials.json`을 읽습니다. 다운로드한 OAuth 클라이언트 JSON을 그 이름으로 두어야 합니다. 로컬 사본은 배포 후 지웠으므로, 다시 발급할 때는 Google 인증 플랫폼의 데스크톱 클라이언트에서 JSON을 새로 받습니다. 범위는 `gmail.modify` 하나이고, 브라우저에서는 넷플릭스 메일을 받는 Gmail 계정으로 로그인합니다.

OAuth 동의 화면은 외부 사용자 유형, 프로덕션 게시 상태입니다. 프로덕션 게시에는 브랜딩의 홈페이지와 개인정보처리방침 링크, 그 승인된 도메인이 필요합니다. 두 페이지는 공개 저장소 `kudongku99/netflix-household-auto-update-terms`의 GitHub Pages(`https://kudongku99.github.io/netflix-household-auto-update-terms/`)에 있고, 원본은 `docs/oauth-pages/`입니다. 로고는 올리지 않습니다. 올리면 앱 인증 제출 대상이 됩니다.

최초 배포:

```bash
bash deploy.sh
```

리전은 서울(`asia-northeast3`)입니다. 스크립트는 API 활성화, Secret 생성, Cloud Run 배포, Pub/Sub 토픽·구독, Scheduler 작업 생성, 첫 watch 등록까지 아홉 단계를 한 번에 처리합니다. 생성 명령(`secrets create`, `topics create`, `service-accounts create` 등)이라 재실행 시 "이미 존재함" 오류로 멈춥니다. 중간에 실패하면 처음부터 다시 돌리지 말고 `bash deploy.sh <번호>`로 실패한 단계부터 이어서 실행합니다. 스크립트에 IAM 바인딩이 들어 있어 Claude Code 자동 모드에서는 사용자가 직접 실행합니다.

새 프로젝트에 배포하며 겪어 스크립트에 반영한 문제:

- 소스 빌드에 쓰이는 기본 compute 서비스 계정에 `roles/run.builder`를 부여합니다. 부여 직후 배포하면 권한이 전파되지 않아 `PERMISSION_DENIED`(소스 zip을 읽지 못함)로 실패하므로, 배포는 30초 간격으로 최대 3번 재시도합니다.
- Cloud Run이 같은 compute 서비스 계정으로 Secret을 읽으므로 `gmail-token`에 `roles/secretmanager.secretAccessor`를 부여합니다.
- 방금 만든 `netflix-invoker`에 곧바로 `run.invoker`를 붙이면 IAM 전파 지연으로 "does not exist" 오류가 납니다. 그래서 10초 간격으로 최대 6번 재시도합니다.
- Pub/Sub 구독과 Scheduler의 OIDC audience는 `/pubsub`, `/renew` 경로를 뺀 서비스 주소로 지정합니다.

토큰 재발급 (인증 오류가 나거나 OAuth 설정을 바꾼 경우): `get_token.py`를 다시 실행한 뒤 Secret에 새 버전을 올리고, 새 리비전을 띄워 환경변수를 다시 읽게 합니다.

```bash
gcloud secrets versions add gmail-token --data-file=token.json --project netflix-household-1027
gcloud run services update netflix-household --region asia-northeast3 --update-secrets GMAIL_TOKEN=gmail-token:latest --project netflix-household-1027
```

새 버전을 올리고 확인이 끝나면 로컬 `token.json`, `credentials.json`은 다시 지웁니다.

코드 수정 후 재배포:

```bash
gcloud run deploy netflix-household --source . --region asia-northeast3 --no-allow-unauthenticated --memory 2Gi --cpu 1 --concurrency 1 --max-instances 1 --timeout 120 --set-env-vars "PROJECT_ID=netflix-household-1027,TOPIC_ID=gmail-netflix" --set-secrets "GMAIL_TOKEN=gmail-token:latest" --project netflix-household-1027
```

Cloud Build 업로드 대상은 `.gcloudignore`의 허용 목록(`Dockerfile`, `requirements.txt`, `src/` 전체, 단 `__pycache__` 제외)뿐입니다. 그래서 `token.json`, `credentials.json`은 `.gitignore`와 상관없이 올라가지 않습니다. 새 모듈은 `src/` 안에 만들면 Dockerfile이나 `.gcloudignore`를 고치지 않아도 이미지에 들어갑니다. 반대로 이미지에 들어가면 안 되는 파일(테스트, 로컬 스크립트, 자격증명)은 `src/`에 두지 않습니다. 확인은 `gcloud meta list-files-for-upload`로 합니다.

의존성은 `requirements.txt`에 간접 의존성까지 전부 `==`로 고정합니다(지금 33개, 직접 의존성은 flask, gunicorn, google-api-python-client, google-auth, playwright). 특히 playwright는 버전마다 크로미움이 바뀌어 버튼 클릭 동작이 달라질 수 있으므로, 올릴 때는 의도적으로 하나씩 올리고 TV 테스트로 확인합니다. Docker 베이스 이미지도 `python:3.12.x-slim` 태그와 함께 digest로 고정합니다(지금 `python:3.12.16-slim`). 크로미움은 헤드리스 셸만(`playwright install --with-deps --only-shell chromium`) 설치합니다. 태그는 사람이 읽기 위한 것이고 실제로는 digest가 쓰입니다. 올릴 때는 태그와 digest를 함께 바꿉니다. 새 조합이 리눅스 + Python 3.12에서 해석되는지는 실제 설치 없이 확인할 수 있습니다(`manylinux2014`만 주면 최신 greenlet 휠을 못 찾으므로 `manylinux_2_28`을 함께 줍니다):

```bash
.venv/bin/pip install --dry-run --ignore-installed --target /tmp/resolve --platform manylinux_2_28_x86_64 --platform manylinux2014_x86_64 --python-version 3.12 --only-binary=:all: -r requirements.txt
```

린트, 포맷, 타입 검사, 테스트 (설정은 모두 `pyproject.toml`, 대상 버전은 Docker와 같은 py312, 줄 길이 100). 코드를 고친 뒤에는 넷 다 통과시킵니다:

```bash
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/mypy && .venv/bin/pytest -q
```

커밋할 때는 `.githooks/pre-commit`이 위 네 가지(ruff 검사, 포맷 검사, mypy, pytest)를 돌리고 하나라도 실패하면 커밋을 막습니다. git은 hook 경로 설정을 저장소에 담지 않으므로 새로 클론한 곳에서는 한 번 켜 줍니다:

```bash
git config core.hooksPath .githooks
```

VS Code는 `.vscode/settings.json`에서 ruff 확장(`charliermarsh.ruff`)을 파이썬 기본 포맷터로 지정해 저장할 때 포맷합니다. `ruff.importStrategy`가 `fromEnvironment`라 확장에 내장된 ruff가 아니라 `.venv`에 고정된 버전을 씁니다. import 정렬과 자동 수정(`ruff check --fix`)도 저장할 때 함께 적용되는데, `explicit`이라 직접 저장(Cmd+S)할 때만 돌고 자동 저장 때는 돌지 않습니다.

`requirements-dev.txt`는 Docker 이미지에 들어가지 않습니다. 운영 Python은 3.12이고 `.python-version`에도 적어 둡니다. 로컬 `.venv`가 더 높은 버전이더라도 3.13 이상에만 있는 문법이나 API는 쓰지 않습니다.

- ruff는 기본 규칙에 더해 이름 규칙(`N`), 불필요한 복잡도(`SIM`), 반환 일관성(`RET`), 타입 힌트 누락(`ANN`)을 검사합니다.
- mypy는 strict 모드로 `src/`와 `tests/`를 검사합니다. 타입 정보가 없는 외부 라이브러리 두 곳만 예외로 두었습니다. `googleapiclient`는 import를 검사하지 않고, `google.oauth2`는 타입 없는 함수 호출을 허용합니다. 그래서 `service.users().messages()...` 같은 Gmail API 호출은 타입 검사가 되지 않습니다.
- pytest 테스트는 `tests/`에 있고, `pythonpath = ["src"]` 설정으로 운영과 같은 `import household`를 씁니다. 테스트 파일은 모듈을 따라 나눕니다. `test_email_parser.py`는 메일 파싱을, `test_household.py`는 만료 판단 같은 순수 함수와 제한 시간 설정의 일치를, `test_confirm_household_emails.py`는 Gmail API(`MagicMock`)와 `_click_confirm_button`(monkeypatch)을 가짜로 바꿔 전체 흐름(만료 건너뛰기, 성공한 메일만 읽음 처리, 건너뛴 이유 로그, 한 메일의 오류가 나머지를 막지 않음, 제한 시간이 부족하면 남은 메일을 미룸)을 검사합니다. `test_structured_logging.py`는 로그 JSON 형식을, `test_main.py`는 환경변수를 넣고 `main`을 새로 import해 household 함수를 가짜로 바꾼 뒤 응답 코드(204/500/200)와 토픽 이름을 검사합니다. 실제 Gmail API 응답과 Playwright 클릭은 테스트하지 않습니다.

Gmail 조회와 버튼 클릭은 TV에서 이용가구 업데이트 메일을 실제로 요청한 뒤 Cloud Run 로그를 확인하는 방식으로만 검증할 수 있습니다:

```bash
gcloud logging read 'resource.type="cloud_run_revision" AND resource.labels.service_name="netflix-household"' --project netflix-household-1027 --freshness=30m --limit 30 --format='table(timestamp.date("%H:%M:%S",tz=LOCAL), severity, httpRequest.requestUrl, httpRequest.status, jsonPayload.message, textPayload)'
```

앱 로그는 JSON에 `severity`와 `message`만 있어 Cloud Logging이 심각도는 읽되 메시지는 `jsonPayload.message`가 아니라 `textPayload`에 담습니다. 그래서 위 명령은 두 칸을 함께 보여 주고, 로그 문구로 거를 때는 `textPayload:"확인 완료"`처럼 씁니다. 메일 한 통에도 Gmail 알림이 4~8번 옵니다(도착, 서비스의 읽음 처리 같은 라벨 변경마다). 첫 요청이 콜드 스타트와 크로미움 실행으로 6~13초, 나머지는 1초 안팎이며 모두 204면 정상입니다. 버튼이 없는 넷플릭스 메일은 읽지 않음으로 남아 하루 동안 알림마다 다시 조회되고, 15분 뒤부터 "만료되어 건너뜀"이 반복해서 찍힙니다.

서비스 URL을 브라우저로 열면 403이 찍히는데, 비공개 서비스라 정상입니다.

## 작업 시 주의사항

- `_CONFIRM_SELECTOR`(`button[data-uia="set-primary-location-action"]`)는 오픈소스 auto-flixer 기준이며, 넷플릭스가 페이지를 바꾸면 깨집니다. "확인 버튼을 찾지 못함" 로그에 찍힌 페이지 주소와 제목이 원인 파악의 단서입니다.
- Playwright 크로미움 때문에 Cloud Run 메모리 2Gi, 동시성 1, 최대 인스턴스 1로 잡혀 있습니다. 브라우저 실행은 `--no-sandbox`가 필요합니다.
- `token.json`, `credentials.json`은 Gmail 접근 권한을 담고 있으므로 커밋하지 않습니다. 배포 후 로컬과 Cloud Shell의 사본도 삭제합니다.
- 넷플릭스 약관은 자동화 접근을 금지하고 있어 계정 제재 위험이 있습니다.
- OAuth 동의 화면이 테스트 상태면 리프레시 토큰이 7일 뒤 만료됩니다. "일주일 뒤 갑자기 인증 오류"가 나면 이것부터 의심합니다.
- 로컬에서 도는 버전(IMAP IDLE, Pub/Sub 풀 구독)도 검토했지만 컴퓨터가 켜져 있어야 해서 채택하지 않았습니다. 그 코드는 저장소에 없습니다. 서버리스 구조를 유지합니다.
- 변수, 함수, 매개변수 이름에 약어를 쓰지 않고 풀어서 씁니다(`creds` → `credentials`, `res` → `response`, `msg` → `message`). URL, HTML, ID, JSON처럼 그 자체가 용어로 굳은 것과, 외부 API나 부모 클래스가 정한 이름(Gmail API의 `userId`, `HTMLParser`의 `attrs`)은 예외입니다.
- 함수와 메서드에는 매개변수와 반환값의 타입 힌트를 붙이고, 빈 리스트나 `None`으로 초기화해 타입이 드러나지 않는 필드에도 붙입니다. 운영 버전인 3.12 문법(`list[str]`, `str | None`)을 씁니다. 힌트는 실행 시 검사되지 않으므로 mypy로 확인합니다.
- 다른 모듈에서 쓰지 않는 함수, 클래스, 상수는 이름 앞에 `_`를 붙입니다. 공개 이름은 `household`의 `build_gmail_service`, `confirm_household_emails`, `renew_watch`와 `email_parser`의 `decode_message`, `find_button_url`, `structured_logging`의 `configure_logging`뿐입니다. 테스트에서는 `_` 이름을 import해도 됩니다. `main.py`는 진입점이라 적용하지 않습니다.
- 사용자에게 답할 때 한자는 쓰지 않습니다.
- IAM 바인딩을 추가하는 gcloud 명령(`add-iam-policy-binding`)은 Claude Code 자동 모드에서 차단됩니다. 명령을 준비해 사용자에게 직접 실행을 요청합니다.
