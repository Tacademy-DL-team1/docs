# Notion 회의록 PR 자동화

Notion에 작성한 회의록을 OpenAI로 먼저 정리해 Notion 본문에 `정리본` 섹션을 만들고, 사람이 확인한 뒤 기존 팀 프로세스에 맞춰 GitHub Issue, 브랜치, 커밋, PR을 생성합니다.

## 1. Notion 준비

1. Notion Integration을 만들고 Internal Integration Secret을 발급합니다.
2. 회의록 데이터베이스를 Integration에 공유합니다.
3. 데이터베이스 ID를 복사합니다.

권장 속성:

| 속성 | 타입 | 설명 |
| --- | --- | --- |
| `회의 주제` | title | 회의록 제목 |
| `날짜` | date | 회의 날짜 |
| `회의 요약` | rich text | 회의록 요약 |
| `상태` | select | 자동화 대상 관리 |
| `GitHub Issue` | url | 자동 생성된 Issue 링크 |
| `GitHub PR` | url | 자동 생성된 PR 링크 |

`상태` select에는 최소한 아래 값을 추가합니다.

- `정리 필요`
- `정리 완료`
- `PR 생성`
- `완료`

## 2. 환경변수 설정

PowerShell에서 아래처럼 설정합니다.

```powershell
$env:NOTION_TOKEN="secret_xxx"
$env:OPENAI_API_KEY="sk_xxx"
$env:GITHUB_TOKEN="github_pat_xxx"
$env:NOTION_MEETING_DATABASE_ID="<database_id>"
```

Notion URL에 포함된 데이터베이스 식별자를 사용하며, 뒤의 `v=...` 값은 뷰 ID이므로 사용하지 않습니다. 실제 토큰과 데이터베이스 ID는 문서에 기록하거나 커밋하지 마세요.

## 3. Notion 안에 정리본 생성

```powershell
python scripts\refine_notion_meeting.py --overwrite
```

`상태 = 정리 필요`인 회의록을 읽어서 같은 Notion 페이지 하단에 `정리본` 섹션을 추가합니다. 완료되면 상태를 `정리 완료`로 바꿉니다.

로컬에 미리보기 Markdown도 남기고 싶으면:

```powershell
python scripts\refine_notion_meeting.py --overwrite --output-dir tmp_refined
```

## 4. Notion에서 확인

Notion 페이지에 생성된 `정리본` 섹션을 사람이 확인하고 필요하면 직접 수정합니다. GitHub에는 이 `정리본` 내용만 올라갑니다.

## 5. 로컬에서 파일만 테스트

```powershell
python scripts\sync_notion_meeting_pr.py --local-only
```

`상태 = 정리 완료`인 회의록의 `정리본` 섹션을 읽어서 `meeting_log/YYMMDD_meeting.md` 파일로 저장합니다.

## 6. Issue, 브랜치, PR까지 생성

```powershell
python scripts\sync_notion_meeting_pr.py
```

자동화는 아래 순서로 동작합니다.

1. Notion에서 `상태 = 정리 완료`인 회의록 조회
2. Notion의 `정리본` 섹션만 읽어서 `meeting_log/YYMMDD_meeting.md` 내용 생성
3. GitHub Issue 생성
4. `docs/issue-{이슈번호}-{파일명}` 브랜치 생성
5. 파일 커밋
6. PR 생성
7. Notion의 `상태`를 `PR 생성`으로 변경
8. `GitHub Issue`, `GitHub PR` 속성에 링크 저장

## 정리 방식

`refine_notion_meeting.py`는 OpenAI Responses API의 Structured Outputs 방식으로 회의록을 JSON 구조로 정리한 뒤, Notion 블록으로 다시 렌더링합니다.

정리 규칙:

- 원문에 없는 사실 추가 금지
- 불확실한 내용은 `확인 필요` 섹션으로 분리
- Notion 안내문, 빈 placeholder, 중복 Summary 제거
- 회의 안건, 주요 논의 내용, 회의 결과, To-Do 분리
- 기존 파일명 규칙인 `YYMMDD_meeting.md` 유지

## 7. GitHub Actions에서 실행

워크플로는 두 개입니다.

| 워크플로 | 역할 |
| --- | --- |
| `Refine Notion meeting logs` | `정리 필요` 회의록을 OpenAI로 정리하고 Notion에 `정리본` 생성 |
| `Create meeting log PR from Notion` | `정리 완료` 회의록의 `정리본`으로 Issue/브랜치/PR 생성 |

GitHub 저장소의 `Settings > Secrets and variables > Actions`에서 아래 Secret을 설정합니다.

| Secret | 값 |
| --- | --- |
| `NOTION_TOKEN` | Notion Integration Secret |
| `NOTION_MEETING_DATABASE_ID` | 회의록 데이터베이스 ID |
| `OPENAI_API_KEY` | OpenAI API Key |

선택 Variable:

| Variable | 기본값 |
| --- | --- |
| `OPENAI_MODEL` | `gpt-5-mini` |

그 다음 Actions 탭에서 아래 순서로 수동 실행합니다.

1. `Refine Notion meeting logs`
2. Notion에서 `정리본` 확인
3. `Create meeting log PR from Notion`

## 8. 파일명 규칙

기존 규칙을 유지해서 `YYMMDD_meeting.md`로 생성합니다.

## 주의

GitHub PR까지 만들려면 `GITHUB_TOKEN`에 `repo` 권한이 필요합니다. GitHub Actions에서 실행할 때는 기본 `secrets.GITHUB_TOKEN`을 사용합니다.
