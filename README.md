# 넷플릭스 이용가구 자동 확인

Gmail에 넷플릭스 이용가구 업데이트 메일이 오면 Google Cloud가 몇 초 안에 확인 버튼을 대신 누르는 서버리스 서비스입니다. 컴퓨터와 휴대폰이 꺼져 있어도 동작합니다.

## 동작 방식

```
[알림 경로]
Gmail watch → Pub/Sub 토픽 gmail-netflix → push 구독 → Cloud Run /pubsub
→ 메일 속 "네, 본인입니다" 링크를 헤드리스 크롬으로 열고 확인 버튼 클릭 → 메일 읽음 처리

[watch 갱신 경로]
Cloud Scheduler (매일 06:00) → Cloud Run /renew → Gmail watch 연장
```

확인에 성공한 메일은 읽음 처리해 중복을 막고, 받은 지 15분이 지난 메일은 건너뜁니다. 인증 링크가 15분 뒤 만료되기 때문입니다.

| 파일                        | 역할                                                                               |
| --------------------------- | ---------------------------------------------------------------------------------- |
| `src/main.py`               | Cloud Run 진입점. 환경변수를 읽고 `/pubsub`, `/renew` 요청을 `household.py`로 넘김 |
| `src/household.py`          | 실제 로직. `/pubsub`에서 메일 조회와 버튼 클릭, `/renew`에서 watch 갱신            |
| `src/email_parser.py`       | 메일 원문에서 "네, 본인입니다" 버튼 링크를 찾음                                    |
| `src/structured_logging.py` | 로그를 Cloud Logging이 읽는 JSON 한 줄(`severity`, `message`)로 출력               |
| `Dockerfile`                | `python:3.12.16-slim`(digest 고정) + Playwright 헤드리스 크로미움 이미지           |
| `requirements.txt`          | 간접 의존성까지 33개 고정. 직접 의존성은 flask, gunicorn, google-api-python-client, google-auth, playwright |
| `requirements-dev.txt`      | 운영 의존성 + ruff, mypy, pytest. 이미지에는 들어가지 않음                         |
| `get_token.py`              | 로컬에서 실행해 Gmail OAuth 토큰(`token.json`) 발급                                |
| `deploy.sh`                 | API 활성화부터 첫 watch 등록까지 9단계를 한 번에 실행. `bash deploy.sh <번호>`로 이어서 실행 |
| `tests/`                    | pytest 테스트와 익명화한 실제 이용가구 메일 픽스처                                 |
| `docs/oauth-pages/`         | OAuth 동의 화면 게시에 쓰는 홈페이지와 개인정보처리방침 원본                       |

## 설정

### 1. GCP 프로젝트 준비

Cloud Console에서 프로젝트를 만들고 결제 계정을 연결합니다. Cloud Run과 Cloud Build에 결제 계정이 필요하지만 이 사용량은 무료 범위 안입니다.

### 2. OAuth 클라이언트 생성

- Google 인증 플랫폼에서 OAuth 동의 화면을 "외부"로 만들고 게시 상태를 **프로덕션**으로 바꿉니다. 테스트 상태면 리프레시 토큰이 7일 후 만료됩니다. 토큰 발급 전에 바꿔야 합니다.
- 프로덕션으로 게시하려면 브랜딩에 앱 이름과 이메일 외에 **홈페이지와 개인정보처리방침 링크, 그 도메인을 등록한 승인된 도메인**이 필요합니다. 비어 있으면 "앱 게시" 버튼이 꺼진 채로 남습니다. 이 저장소는 `docs/oauth-pages/`의 두 페이지를 별도 공개 저장소의 GitHub Pages에 올리고, 승인된 도메인에 `<GitHub 아이디>.github.io`를 넣었습니다. 로고는 올리지 않습니다. 올리면 앱 인증 제출 대상이 됩니다.
- 클라이언트 메뉴에서 **데스크톱 앱** 유형 OAuth 클라이언트를 만들고, 받은 JSON을 `credentials.json`이라는 이름으로 프로젝트 폴더에 둡니다.

### 3. 토큰 발급 (로컬)

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt google-auth-oauthlib
.venv/bin/python get_token.py
```

브라우저에서 넷플릭스 메일을 받는 Gmail 계정으로 로그인합니다. GCP 프로젝트를 만든 계정과 달라도 됩니다. "확인되지 않은 앱" 경고가 나오면 고급 → 이동을 눌러 진행합니다. 요청하는 범위는 `gmail.modify`(메일 읽기와 라벨 수정) 하나입니다.

### 4. 배포

gcloud가 설치된 로컬에서 `deploy.sh`의 `PROJECT_ID`를 확인한 뒤 실행합니다. IAM 권한 부여가 들어 있어 Claude Code 자동 모드에서는 막히므로 직접 실행합니다.

```bash
bash deploy.sh
```

스크립트가 API 활성화, Secret Manager에 토큰 저장, 권한 부여, Cloud Run 배포, Pub/Sub 토픽과 push 구독, Scheduler 작업 생성, 첫 watch 등록까지 아홉 단계를 처리합니다. 생성 명령으로 이뤄져 있어 재실행하면 "이미 존재함" 오류로 멈춥니다. 중간에 실패하면 `bash deploy.sh 4`처럼 실패한 단계 번호부터 이어서 실행하세요. 권한 전파 지연에 대비해 Cloud Run 배포와 `run.invoker` 부여는 스스로 재시도합니다.

| 배포 설정        | 값                                                           |
| ---------------- | ------------------------------------------------------------ |
| 리전             | asia-northeast3 (서울)                                       |
| Cloud Run 리소스 | 메모리 2Gi, CPU 1, 동시성 1, 최대 인스턴스 1, 타임아웃 120초 |
| 인증             | 비공개 서비스, 호출 전용 서비스 계정 `netflix-invoker`       |
| Pub/Sub 구독     | `gmail-netflix-push`, ack 기한 120초, 메시지 보존 10분       |
| watch 갱신       | Cloud Scheduler `gmail-watch-renew`, 매일 06:00 (Asia/Seoul) |

배포가 끝나면 로컬과 Cloud Shell에 남은 `token.json`, `credentials.json` 사본을 지웁니다.

## 테스트와 문제 해결

TV에서 이용가구 업데이트 메일을 한 번 요청하고 Cloud Run 로그에서 결과를 확인합니다. 요청한 메일은 서비스가 처리하기 전에 Gmail에서 열지 않습니다. 읽지 않은 메일만 처리 대상입니다. 로그 조회 명령은 `CLAUDE.md`에 있고, 앱 로그 문구는 `textPayload`에 담깁니다. 정상이면 메일 도착 후 10초 안팎에 "확인 완료"가 찍힙니다.

| 증상                                                   | 원인                                                    | 조치                                                                                        |
| ------------------------------------------------------ | ------------------------------------------------------- | ------------------------------------------------------------------------------------------- |
| 로그에 "확인 완료"                                     | 정상 동작                                               | 없음                                                                                        |
| "확인 버튼을 찾지 못함" (WARNING)                      | 로그인 요구, 버튼 구조 변경, 봇 차단                    | 로그의 페이지 주소와 제목으로 원인 파악 후 `_CONFIRM_SELECTOR` 또는 흐름 수정               |
| "만료되어 건너뜀"                                      | 알림이 메일 수신 15분 뒤에 도착, 또는 버튼 없는 넷플릭스 메일이 읽지 않음으로 남아 알림마다 다시 조회됨 | 같은 메일 ID가 반복되면 후자라 정상. 이용가구 메일에서 경과 시간이 길면 Pub/Sub 지연이나 인스턴스 부팅 지연 확인 |
| "메일 처리 중 오류" (ERROR)                            | 페이지 로드 시간 초과, Gmail API 오류 등                | 나머지 메일은 계속 처리되고 500으로 끝나 Pub/Sub가 재전송함. 반복되면 로그의 traceback 확인 |
| "요청 제한 시간이 부족해 다음 알림으로 미룸" (WARNING) | 앞 메일 처리가 오래 걸림                                | Pub/Sub 재전송으로 자동 재시도됨. 반복되면 페이지 로드가 느린 원인 확인                     |
| "확인 링크 없음"                                       | 이용가구 메일이 아닌 넷플릭스 메일, 또는 버튼 문구 변경 | 이용가구 메일인데 찍혔다면 `_BUTTON_TEXTS` 수정                                             |
| 아무 로그 없음                                         | watch 미등록 또는 Pub/Sub 권한 누락                     | Scheduler 작업 수동 실행, 토픽의 `gmail-api-push` 게시자 권한 확인                          |
| 일주일 뒤 인증 오류                                    | OAuth 동의 화면이 테스트 상태                           | 프로덕션 전환 후 토큰 재발급, Secret 새 버전 등록                                           |
| 배포 중 `PERMISSION_DENIED` (소스를 읽지 못함)         | 방금 부여한 `run.builder`가 아직 전파되지 않음          | 스크립트가 재시도함. 그래도 실패하면 1~2분 뒤 `bash deploy.sh 4`                            |
| OAuth "앱 게시" 버튼이 꺼져 있음                       | 브랜딩의 홈페이지·개인정보처리방침 링크, 승인된 도메인 누락 | 두 링크와 도메인을 채우고 저장한 뒤 대상 화면 새로고침                                  |
| Gmail API 403 "has not been used in project"           | 프로젝트에서 Gmail API가 꺼져 있음                      | `deploy.sh` 1단계가 켬. 배포 전에 토큰을 시험하려면 `gcloud services enable gmail.googleapis.com` |
| `No module named google_auth_oauthlib`                 | 가상환경에 설치하지 않음                                | `.venv/bin/pip install google-auth-oauthlib`                                                |
| 서비스 URL을 브라우저로 열면 403                       | 비공개 서비스                                           | 정상                                                                                        |

## 주의사항

- 확인 버튼 선택자 `button[data-uia="set-primary-location-action"]`는 오픈소스 auto-flixer 기준이며, 넷플릭스가 페이지를 바꾸면 달라질 수 있습니다.
- 넷플릭스 약관은 자동화된 접근을 금지하고 있어 계정 제재 위험이 있습니다. 이용가구 확인은 본인이 다른 장소에서 시청할 때를 위한 기능입니다.
- `token.json`과 `credentials.json`은 메일 접근 권한을 담고 있습니다. 저장소에 커밋하지 않습니다(`.gitignore`에 포함).
