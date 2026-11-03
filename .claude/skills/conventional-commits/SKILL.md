---
name: conventional-commits
description: Conventional Commits 1.0.0 규격(type(scope): 설명)에 맞춰 이 프로젝트의 커밋 메시지를 작성한다. 사용자가 "커밋 메시지 만들어줘", "커밋해줘"처럼 커밋을 언급하면 이 스킬을 사용한다.
allowed-tools: Read, Grep, Glob, Bash(git diff:*), Bash(git status:*), Bash(git log:*), Bash(git branch:*), Bash(git add:*), Bash(git commit:*)
---

# 커밋 메시지 작성 (Conventional Commits 1.0.0)

규격 원문: https://www.conventionalcommits.org/ko/v1.0.0/

커밋 로그만 보고 무엇이 왜 바뀌었는지 알 수 있게 하는 것이 목적이다.

## 양식

```
<type>[(scope)][!]: <설명>

[본문]

[꼬리말]
```

## 규칙

- 제목 줄은 `type`, 선택적 `(scope)`, 선택적 `!`, 콜론, 공백, 설명 순서로 쓴다.
- 설명은 한국어 한 줄로, 무엇을 했는지 간결하게 쓴다. 마침표는 붙이지 않고 한자는 쓰지 않는다.
- 제목 줄은 가능하면 50자 안팎으로 유지한다.
- 본문은 제목 줄 다음에 빈 줄 한 개를 두고 시작한다. 무엇을 왜 바꿨는지 자유롭게 쓴다.
- 꼬리말은 본문 다음에 빈 줄 한 개를 두고 `토큰: 값` 또는 `토큰 #값` 형식으로 쓴다. 토큰의 공백은 `-`로 대체한다(예: `Reviewed-by`).
- 하위 호환이 깨지는 변경은 type 또는 scope 뒤에 `!`를 붙이거나, 꼬리말에 `BREAKING CHANGE: <설명>`을 쓴다. 토큰은 대문자여야 한다.

## type

| type | 쓰는 때 | SemVer |
| --- | --- | --- |
| `feat` | 새 기능 추가 | MINOR |
| `fix` | 버그 수정 | PATCH |
| `docs` | 문서만 변경 | - |
| `style` | 동작에 영향 없는 서식 변경(공백, 따옴표 등) | - |
| `refactor` | 기능 변화 없는 구조 개선 | - |
| `perf` | 성능 개선 | - |
| `test` | 테스트 추가, 수정 | - |
| `build` | 빌드 설정, 의존성 변경(`pyproject.toml`, `requirements*.txt`, `Dockerfile`) | - |
| `ci` | CI 설정 변경 | - |
| `chore` | 위에 해당하지 않는 잡무(hook, 에디터 설정 등) | - |

## scope

이 프로젝트의 파일 구성에 맞춰 고른다. 여러 영역에 걸치면 생략한다.

| scope | 대상 |
| --- | --- |
| `parser` | `src/email_parser.py`와 그 테스트 |
| `household` | `src/household.py`와 그 테스트 |
| `main` | `src/main.py` |
| `logging` | `src/structured_logging.py`와 그 테스트 |
| `deploy` | `deploy.sh`, `Dockerfile`, `.gcloudignore`, `get_token.py` |
| `docs` | `README.md`, `CLAUDE.md`, `docs/` |

## 작업 순서

1. 변경사항을 확인한다. 특별한 지시가 없으면 스테이징된 것만 대상으로 한다.
   - `git status`, `git diff --staged`
   - 스테이징된 변경이 없으면 사용자에게 알리고 `git add` 할 범위를 확인한다.
2. 변경이 서로 다른 목적을 섞고 있으면 커밋을 나누자고 제안한다. 한 커밋에는 한 가지 목적만 담는다.
3. 가장 알맞은 type과 scope를 골라 위 양식으로 메시지를 작성해 사용자에게 보여 준다.
4. 사용자가 확인하면 커밋한다. 사용자가 요청하기 전에는 커밋하지 않는다.
5. 환경이 커밋 메시지 끝에 붙이라고 지정한 공동 작성자 줄이 있으면, 꼬리말 맨 끝에 붙인다.

## 이 프로젝트에서 지킬 것

- `token.json`, `credentials.json`, OAuth 토큰, 넷플릭스 링크의 `nftoken` 값을 커밋 메시지(본문 포함)에 쓰지 않는다. 실제 이메일 주소나 이름도 쓰지 않는다.
- `token.json`, `credentials.json` 같은 자격증명 파일이 스테이징되어 있으면 커밋하지 말고 사용자에게 알린다.
- 테스트 픽스처로 넣는 메일 원문은 익명화가 끝난 것만 커밋한다. 수신 주소, 이름, `g=` ID, `nftoken`이 남아 있으면 커밋하지 말고 사용자에게 알린다.
- pre-commit hook이 ruff, mypy, pytest를 돌려 실패하면 커밋이 막힌다. `--no-verify`로 우회하지 말고 원인을 고친 뒤 다시 커밋한다.

## 샘플

```
docs: 로드맵에 픽스처 익명화 기준 추가
```

```
build: 검사 도구와 pre-commit hook 설정 추가

ruff, mypy, pytest 설정을 pyproject.toml에 모으고, 네 가지 검사를 통과해야 커밋되도록 했다.
```

```
feat(parser): 메일에서 본인 확인 버튼 링크 추출

링크 텍스트가 "네, 본인입니다" 또는 "Yes, This Was Me"인 a 태그의 href를 반환한다.
```

```
fix(household)!: 만료 판단이 현재 시각을 인자로 받도록 변경

BREAKING CHANGE: 만료 판단 함수를 호출하는 곳에서 기준 시각을 넘겨야 한다.
```
